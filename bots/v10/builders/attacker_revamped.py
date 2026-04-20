from enum import Enum

from cambc import Controller, Direction, EntityType, Position
from utils.attacker_states.approach import _approach as _approach_state
from utils.attacker_states.replace import (
    _replace as _replace_state,
    _target_still_valid,
)
from utils.attacker_states.scan import _scan as _scan_state
from utils.d_star import DStarLite
from utils.raw_map_representation import CORE_ENEMY, EnvironmentMap, WALL

# Builders cannot walk through the enemy core, and this attacker never targets
# the enemy core itself (it hijacks conveyors near enemy harvesters), so block
# CORE_ENEMY statically in the mask — no dynamic blocker needed.
_ATTACK_BLOCK_MASK = (1 << WALL) | (1 << CORE_ENEMY)


class AttackState(Enum):
    __slots__ = ()

    SCAN = "scan"              # Probing for an enemy harvester→conveyor to hijack
    APPROACH = "approach"      # Walking onto a locked-in target conveyor
    REPLACE = "replace"        # On-tile: fire conveyor → step off → sentinel


class AttackerRevamped:
    """Disruption-focused attacker.

    Hijacks enemy conveyors that feed titanium harvesters: walks onto the
    conveyor, fires it down with the own-tile attack, steps off, and drops a
    sentinel on the now-empty tile facing the enemy core.
    """

    def __init__(self, core_pos: Position):
        self.state = AttackState.SCAN
        self.core_pos = core_pos
        self.current_pos: Position = core_pos

        # Enemy-core probing for SCAN's idle behaviour.
        self.enemy_core_candidates: list[Position] = []
        self.enemy_core_candidate_idx = 0
        self.enemy_core_pos: Position | None = None

        # Post-core-found orbit waypoints (built lazily once enemy_core_pos is set).
        self.orbit_points: list[Position] | None = None
        self.orbit_idx = 0

        # Locked-in target
        self.target_conveyor: Position | None = None
        self.sentinels_placed = 0

        # Hard-failed targets: never re-pick these.
        self.blacklist: set[tuple[int, int]] = set()

        # On-tile attack stall detection — blacklist if HP stays above half
        # after 10 firing ticks (the belt is being out-healed).
        self._attack_target_key: tuple[int, int] | None = None
        self._attack_turns = 0
        self._attack_max_hp = 0

        self._env_map: EnvironmentMap | None = None
        self._planner: DStarLite | None = None
        self._planner_goal: tuple[int, int] | None = None
        self.target_pos: Position | None = None  # for debug lines

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
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        blockers.append((p.x + dx, p.y + dy))

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

    # ---------- state handlers (delegate to utils.attacker_states) ----------

    def _scan(self, c: Controller):
        _scan_state(self, c)

    def _approach(self, c: Controller):
        _approach_state(self, c)

    def _replace(self, c: Controller):
        _replace_state(self, c)

    # ---------- debug ----------

    def _draw_debug(self, c: Controller):
        state_colors = {
            AttackState.SCAN: (0, 180, 255),
            AttackState.APPROACH: (0, 255, 0),
            AttackState.REPLACE: (255, 0, 0),
        }
        r, g, b = state_colors.get(self.state, (255, 255, 255))
        c.draw_indicator_dot(self.current_pos, r, g, b)
        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, r, g, b)

    # ---------- main loop ----------

    def run(self, c: Controller):
        if self._env_map is None:
            self._env_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        self._env_map.update(c)

        # Seed enemy-core candidates once (SCAN uses these when idle).
        if not self.enemy_core_candidates:
            W, H = c.get_map_width(), c.get_map_height()
            cx, cy = self.core_pos.x, self.core_pos.y
            self.enemy_core_candidates = [
                Position(W - 1 - cx, H - 1 - cy),  # rotational
                Position(W - 1 - cx, cy),          # horizontal
                Position(cx, H - 1 - cy),          # vertical
            ]

        # Resolve the enemy core: prefer symmetry-deduced centre; fall back to
        # direct sight for the rare case where we spot it before the map has
        # enough data to narrow symmetry.
        if self.enemy_core_pos is None:
            self.enemy_core_pos = self._env_map.enemy_core_centre(self.core_pos)
        if self.enemy_core_pos is None:
            for eid in c.get_nearby_buildings():
                if (c.get_entity_type(eid) == EntityType.CORE
                        and c.get_team(eid) != c.get_team()):
                    self.enemy_core_pos = c.get_position(eid)
                    break

        self.current_pos = c.get_position()

        # Drop stale targets before dispatching to a state handler.
        if self.target_conveyor is not None and not _target_still_valid(self, c):
            self.blacklist.add((self.target_conveyor.x, self.target_conveyor.y))
            self.target_conveyor = None
            self._planner_goal = None
            self.state = AttackState.SCAN

        # Sequential (not elif) so SCAN→APPROACH and APPROACH→REPLACE can
        # both fire in the same tick.
        if self.state == AttackState.SCAN:
            self._scan(c)
        if self.state == AttackState.APPROACH:
            self._approach(c)
        if self.state == AttackState.REPLACE:
            self._replace(c)

        # self._draw_debug(c)
