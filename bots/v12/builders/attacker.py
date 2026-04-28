import os
import uuid

from cambc import Controller, Direction, EntityType, Position
from utils.attacker_states.replace import replace, target_still_valid
from utils.attacker_states.scan import scan
from utils.attacker_states.state import AttackState
from utils.pathfinding.d_star import DStarLite
from utils.map.raw_map_representation import (
    CORE_ENEMY,
    CORE_OWN,
    EnvironmentMap,
    Symmetry,
    WALL,
)
from utils.comms.broadcaster import Broadcaster
from utils.comms.for_builder_bot import BuilderBotMessages
from utils.healing import try_heal_nearby_bot

# Attacker never pathfinds into the enemy core — block CORE_ENEMY statically.
_ATTACK_BLOCK_MASK = (1 << WALL) | (1 << CORE_ENEMY)
# Tiles where neither a builder bot nor a movable building can exist — skip
# the per-tile controller cascade in _search's blocker scan.
_SEARCH_TERRAIN_SKIP_MASK = (1 << WALL) | (1 << CORE_OWN) | (1 << CORE_ENEMY)
_LAUNCHER_RING = (
    (-1, -1), (-1, 0), (-1, 1),
    ( 0, -1), ( 0, 0), ( 0, 1),
    ( 1, -1), ( 1, 0), ( 1, 1),
)

# Per-tile building classification cache. Buildings are built/destroyed orders
# of magnitude less often than bots move, so we re-verify with a small TTL
# instead of polling get_tile_building_id + get_entity_type every turn.
# Trade-off: a launcher built on a previously-empty tile is invisible for up
# to _BLD_TTL turns. With TTL=3 that's a 1–3 turn delay before the planner
# routes around the new 3x3 ring — acceptable because the HP-loss blacklist
# at attacker.run already kicks in if we actually take a hit.
_BLD_TTL = 3
_BLD_NONE = 1   # no building / road / marker / non-blocker
_BLD_HARV = 2   # HARVESTER (any team) — blocks
_BLD_ELAU = 3   # enemy LAUNCHER — blocks self + 3x3 ring
_BLD_OTHER = 4  # friendly LAUNCHER, conveyor, etc. — does not block


# Profiling is only available locally. AWS runners ship a stripped-down CPython
# without _lsprof (the C extension cProfile depends on), so we probe for it
# capability-style rather than sniffing env vars (which the sandbox may hide).
try:
    import cProfile
    _PROFILER = cProfile.Profile()
    _PROFILE_DIR = "/tmp/attacker_profiles"
    _PROFILE_ID = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    _PROFILE_PATH = os.path.join(_PROFILE_DIR, f"attk_{_PROFILE_ID}.pstats")
    _PROFILE_CALLS = 0
    _PROFILE_DUMP_EVERY = 100
    os.makedirs(_PROFILE_DIR, exist_ok=True)
    _PROFILE_ENABLED = True
except ImportError:
    _PROFILE_ENABLED = False


class Attacker:
    """Disruption-focused attacker"""

    def __init__(self, core_pos: Position):
        self.state = AttackState.SCAN
        self.core_pos = core_pos
        self.current_pos: Position = core_pos

        self.enemy_core_candidates: list[Position] = []
        self.enemy_core_candidate_idx = 0
        self.enemy_core_pos: Position | None = None

        # Post-core-found orbit waypoints (built lazily once enemy_core_pos is set).
        self.orbit_points: list[Position] | None = None
        self.orbit_idx = 0
        self._orbit_pursuit_idx: int | None = None
        self._orbit_pursuit_round: int = 0

        self.target_conveyor: Position | None = None

        # Hard-failed targets: skip for _BLACKLIST_TTL turns then retry.
        self.blacklist: dict[tuple[int, int], int] = {}

        # On-tile attack stall detection — blacklist if HP stays above half
        # after 10 firing ticks (the belt is being out-healed).
        self._attack_target_key: tuple[int, int] | None = None
        self._attack_turns = 0
        self._attack_max_hp = 0

        self._env_map: EnvironmentMap | None = None
        self._planner: DStarLite | None = None
        self._planner_goal: tuple[int, int] | None = None
        self.target_pos: Position | None = None  # for debug lines
        # Per-turn vision cache. run() populates once via get_nearby_tiles, then
        # update() and _search consume it instead of issuing a second
        # controller call (which would also re-allocate ~70 Position tuples).
        self._tiles: list[Position] = []
        # Per-tile building classification cache, lazily sized once env_map is
        # constructed (we don't know map dims at __init__).
        # Refreshed for every visible tile every _BLD_TTL rounds rather than
        # per-tile — the round bookkeeping is hoisted to a single per-turn
        # decision, so cache hits cost just a bytearray read + a bool OR.
        self._bld_kind: bytearray | None = None  # 0=unseen, else _BLD_*
        self._bld_last_refresh: int = -10_000  # forces first turn to refresh

        self._hp_prev: int | None = None

        self.broadcaster = Broadcaster()
        self._broadcasted = False
        self._permanent_broadcasts: list[int] = []
        self._broadcasted_claim: tuple[int, int] | None = None

    # ---------- claim broadcast ----------

    def _sync_claim_broadcast(self) -> None:
        """Keep the broadcaster in sync with the current target_conveyor."""
        cur = (self.target_conveyor.x, self.target_conveyor.y) if self.target_conveyor else None
        if cur == self._broadcasted_claim:
            return
        self._broadcasted_claim = cur
        self.broadcaster.clear_broadcasts()
        for msg in self._permanent_broadcasts:
            self.broadcaster.add_broadcast(msg)
        if cur is not None:
            self.broadcaster.add_broadcast(
                BuilderBotMessages.encode_claim_position(self.target_conveyor)
            )

    # ---------- navigation (shared by SCAN's idle probe and APPROACH) ----------

    def _build_blockers(self, c: Controller, env_map: EnvironmentMap) -> list:
        """Return the dynamic-blockers list from current vision.

        Walls/cores are skipped via the env grid mask, building classifications
        are cached for _BLD_TTL rounds, and Position objects are forwarded as
        the (x, y) tuples set_dynamic_blockers expects.
        """
        my_id = c.get_id()
        my_team = c.get_team()
        blockers: list = []
        env_arr = env_map._array
        w_map = env_map._w
        skip_mask = _SEARCH_TERRAIN_SKIP_MASK
        bld_kind = self._bld_kind
        assert bld_kind is not None
        round_now = c.get_current_round()
        # Whole-cache refresh decision is per-turn, not per-tile.
        force_refresh = round_now - self._bld_last_refresh >= _BLD_TTL
        if force_refresh:
            self._bld_last_refresh = round_now
        for p in self._tiles:
            idx = p[1] * w_map + p[0]
            if (skip_mask >> env_arr[idx]) & 1:
                continue
            bot_id = c.get_tile_builder_bot_id(p)
            if bot_id is not None and bot_id != my_id:
                blockers.append(p)
                continue

            kind = bld_kind[idx]
            if force_refresh or kind == 0:
                bld_id = c.get_tile_building_id(p)
                if bld_id is None:
                    kind = _BLD_NONE
                else:
                    et = c.get_entity_type(bld_id)
                    if et == EntityType.HARVESTER:
                        kind = _BLD_HARV
                    elif et == EntityType.LAUNCHER and c.get_team(bld_id) != my_team:
                        kind = _BLD_ELAU
                    else:
                        kind = _BLD_OTHER
                bld_kind[idx] = kind

            if kind == _BLD_HARV:
                blockers.append(p)
            elif kind == _BLD_ELAU:
                # Enemy launchers throw adjacent builders — avoid the 3x3 ring.
                px = p[0]
                py = p[1]
                blockers += [(px + dx, py + dy) for dx, dy in _LAUNCHER_RING]
        return blockers

    def _search(self, c: Controller, target: Position):
        """Navigate toward target with D* Lite and pave if needed."""
        if c.get_move_cooldown() > 0:
            return

        env_map = self._env_map
        assert env_map is not None
        pos = c.get_position()
        goal = (target.x, target.y)
        if self._planner is None or self._planner_goal != goal:
            self._planner = DStarLite(
                env_map, target.x, target.y, block_mask=_ATTACK_BLOCK_MASK
            )
            self._planner_goal = goal
        planner = self._planner

        # Order mirrors baseline: set_position → set_dynamic_blockers →
        # notify_map_changes → step. D* Lite is sensitive to the order
        # (each call may enqueue or recompute predecessors), and reshuffling
        # propagates into different g/rhs values across many turns, which is
        # observable as different game outcomes despite identical scan logic.
        blockers = self._build_blockers(c, env_map)
        planner.set_position(pos.x, pos.y)
        planner.set_dynamic_blockers(blockers)
        planner.notify_map_changes()
        direction = planner.step()

        if direction is None or direction == Direction.CENTRE:
            return

        next_pos = pos.add(direction)
        if c.get_action_cooldown() == 0 and c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(direction):
            c.move(direction)

    # ---------- main loop ----------

    def run(self, c: Controller):
        if _PROFILE_ENABLED:
            global _PROFILE_CALLS
            _PROFILER.enable()
        if self._env_map is None:
            self._env_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
            self._bld_kind = bytearray(self._env_map._w * self._env_map._h)
        # One get_nearby_tiles per turn, shared with _search via self._tiles.
        # Materialise to a list so multiple consumers can iterate it.
        self._tiles = list(c.get_nearby_tiles())
        self._env_map.update(c, tiles=self._tiles)

        if not self._env_map.symmetry_resolved:
            raw = BuilderBotMessages.read_nearby_symmetry(c)
            if raw is not None:
                try:
                    self._env_map.force_symmetry(Symmetry(raw))
                except ValueError:
                    pass
        assumed_centre = self._env_map.assumed_enemy_core_centre(self.core_pos)

        # Direct sight > symmetry inference. None during the ambiguous window
        # (rotational eliminated, H/V still live) so SCAN falls back to
        # enemy_core_candidates rather than a stale guess.
        my_team = c.get_team()
        direct_enemy_core = next(
            (c.get_position(eid) for eid in c.get_nearby_buildings()
             if c.get_entity_type(eid) == EntityType.CORE and c.get_team(eid) != my_team),
            None,
        )
        if (new_ec := direct_enemy_core or assumed_centre) != self.enemy_core_pos:
            self.enemy_core_pos = new_ec
            self.orbit_points = None
            self.orbit_idx = 0
            self._orbit_pursuit_idx = None

        # Symmetry resolving implies assumed_centre is non-None.
        if self._env_map.symmetry is not None and not self._broadcasted:
            assert assumed_centre is not None
            for msg in [
                BuilderBotMessages.encode_symmetry(self._env_map.symmetry.value),
                BuilderBotMessages.encode_core_position(self.core_pos),
                BuilderBotMessages.encode_enemy_core_position(assumed_centre),
            ]:
                self._permanent_broadcasts.append(msg)
                self.broadcaster.add_broadcast(msg)
            self._broadcasted = True

        if not self.enemy_core_candidates:
            W, H, cx, cy = c.get_map_width(), c.get_map_height(), self.core_pos.x, self.core_pos.y
            self.enemy_core_candidates = [
                Position(W - 1 - cx, H - 1 - cy),  # rotational
                Position(W - 1 - cx, cy),          # horizontal
                Position(cx, H - 1 - cy),          # vertical
            ]

        self.current_pos = c.get_position()

        my_id = c.get_id()
        hp_now = c.get_hp(my_id)

        if (prev := self._hp_prev) is not None and hp_now < prev:
            self.blacklist[(self.current_pos.x, self.current_pos.y)] = c.get_current_round()
        self._hp_prev = hp_now

        try_heal_nearby_bot(c, self.current_pos)

        # Drop stale targets before dispatching to a state handler.
        if self.target_conveyor is not None and not target_still_valid(self, c):
            self.blacklist[(self.target_conveyor.x, self.target_conveyor.y)] = c.get_current_round()
            self.target_conveyor = None
            self._planner_goal = None
            self.state = AttackState.SCAN

        print(
            f"[attacker {my_id}] r={c.get_current_round()} "
            f"pos=({self.current_pos.x},{self.current_pos.y}) "
            f"state={self.state.value} "
            f"target={self.target_conveyor} "
            f"ecore={self.enemy_core_pos} "
            f"sym={self._env_map.symmetry} "
            f"acd={c.get_action_cooldown()} mcd={c.get_move_cooldown()} "
            f"hp={hp_now}/{c.get_max_hp(my_id)}"
        )

        # Sequential (not elif) so SCAN→APPROACH and APPROACH→REPLACE can
        # both fire in the same tick.
        if self.state == AttackState.SCAN:
            scan(self, c)
        if self.state == AttackState.APPROACH:
            assert self.target_conveyor is not None
            self.target_pos = self.target_conveyor
            c.draw_indicator_line(self.current_pos, self.target_pos, 255, 0, 255)
            if self.current_pos == self.target_conveyor:
                self.state = AttackState.REPLACE
            else:
                self._search(c, self.target_conveyor)
        if self.state == AttackState.REPLACE:
            replace(self, c)

        self._sync_claim_broadcast()
        self.broadcaster.run(c)
        if _PROFILE_ENABLED:
            _PROFILER.disable()
            _PROFILE_CALLS += 1
            if _PROFILE_CALLS % _PROFILE_DUMP_EVERY == 0:
                _PROFILER.dump_stats(_PROFILE_PATH)
