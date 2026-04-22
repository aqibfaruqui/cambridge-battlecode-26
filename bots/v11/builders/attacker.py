from itertools import product

from cambc import Controller, Direction, EntityType, Position
from utils.attacker_states.replace import replace, target_still_valid
from utils.attacker_states.scan import scan
from utils.attacker_states.state import AttackState
from utils.pathfinding.d_star import DStarLite
from utils.map.raw_map_representation import CORE_ENEMY, EnvironmentMap, Symmetry, WALL
from utils.comms.broadcaster import Broadcaster
from utils.comms.for_builder_bot import BuilderBotMessages

# Attacker never pathfinds into the enemy core — block CORE_ENEMY statically.
_ATTACK_BLOCK_MASK = (1 << WALL) | (1 << CORE_ENEMY)


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

        self._hp_prev: int | None = None

        self.broadcaster = Broadcaster()
        self._broadcasted = False

    # ---------- navigation (shared by SCAN's idle probe and APPROACH) ----------

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

        my_id = c.get_id()
        my_team = c.get_team()
        blockers: list[tuple[int, int]] = []
        for p in c.get_nearby_tiles():
            bot_id = c.get_tile_builder_bot_id(p)
            if bot_id is not None and bot_id != my_id:
                blockers.append((p.x, p.y))
                continue
            bld_id = c.get_tile_building_id(p)
            if bld_id is None:
                continue
            et = c.get_entity_type(bld_id)
            if et == EntityType.HARVESTER:
                blockers.append((p.x, p.y))
                continue
            # Enemy launchers throw adjacent builders — avoid the 3x3 pickup ring.
            if et == EntityType.LAUNCHER and c.get_team(bld_id) != my_team:
                blockers.extend((p.x + dx, p.y + dy) for dx, dy in product((-1, 0, 1), repeat=2))

        self._planner.set_position(pos.x, pos.y)
        self._planner.set_dynamic_blockers(blockers)
        self._planner.notify_map_changes()
        direction = self._planner.step()

        if direction is None or direction == Direction.CENTRE:
            return

        next_pos = pos.add(direction)
        if c.get_action_cooldown() == 0 and c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(direction):
            c.move(direction)

    # ---------- main loop ----------

    def run(self, c: Controller):
        if self._env_map is None:
            self._env_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        self._env_map.update(c)

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
            self.broadcaster.add_broadcast(BuilderBotMessages.encode_symmetry(self._env_map.symmetry.value))
            self.broadcaster.add_broadcast(BuilderBotMessages.encode_core_position(self.core_pos))
            self.broadcaster.add_broadcast(BuilderBotMessages.encode_enemy_core_position(assumed_centre))
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

        if hp_now < c.get_max_hp(my_id) and c.can_heal(self.current_pos):
            c.heal(self.current_pos)

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
            if self.current_pos == self.target_conveyor:
                self.state = AttackState.REPLACE
            else:
                self._search(c, self.target_conveyor)
        if self.state == AttackState.REPLACE:
            replace(self, c)

        self.broadcaster.run(c)
