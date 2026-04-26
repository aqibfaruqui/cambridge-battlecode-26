import os
import sys
import uuid
from enum import Enum

from cambc import Controller, Direction, EntityType, Environment, Position
from utils.map.board import is_ore_axionite, is_ore_titanium
from utils.harvester_states.foundry import _placing_foundry as _foundry_state
from utils.harvester_states.return_to_core import (
    _attack_enemy_under_bot,
    _build_return_step,
    _handle_post_bridge_conveyor,
    _reset_return_state,
)
from utils.harvester_states.seek import (
    _seek as _seek_state,
)
from utils.harvester_states.patrol import (
    _patrol as _patrol_state,
)
from utils.harvester_states.placing_harvester import (
    STEP_ON as _PLACING_STEP_ON,
    _placing_harvester as _placing_harvester_state,
)
from utils.harvester_states.defend import (
    _defend as _defend_state,
    _try_enter_defend,
)
from utils.harvester_states.heal import (
    _heal as _heal_state,
    _try_enter_heal,
)
from utils.pathfinding.movement import DIRECTIONS_4, reached_core
from utils.map.raw_map_representation import EnvironmentMap, Symmetry
from utils.pathfinding.d_star import DStarLite
from utils.comms.broadcaster import Broadcaster
from utils.comms.for_builder_bot import BuilderBotMessages


# Profiling is only available locally. AWS runners ship a stripped-down CPython
# without _lsprof (the C extension cProfile depends on), so we probe for it
# capability-style rather than sniffing env vars (which the sandbox may hide).
try:
    import cProfile
    _PROFILER = cProfile.Profile()
    _PROFILE_DIR = "/tmp/harvester_profiles"
    _PROFILE_ID = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    _PROFILE_PATH = os.path.join(_PROFILE_DIR, f"harv_{_PROFILE_ID}.pstats")
    _PROFILE_CALLS = 0
    _PROFILE_DUMP_EVERY = 100
    os.makedirs(_PROFILE_DIR, exist_ok=True)
    _PROFILE_ENABLED = True
except ImportError:
    _PROFILE_ENABLED = False

class HarvestState(Enum):
    __slots__ = ()

    SEEK = "seek"
    PLACING_HARVESTER = "placing_harvester"
    RETURN = "return"
    PLACING_FOUNDRY = "placing_foundry"
    DEFEND = "defend"
    PATROL = "patrol"
    HEAL = "heal"


_TITANIUM_HARVESTER_TARGET = 3
_AXIONITE_UNLOCK_ROUND = 200


class Harvester:
    def __init__(self, core_pos: Position):
        self.state = HarvestState.SEEK
        self.core_pos = core_pos
        self.current_pos = Position(0, 0)

        self.ti = 0
        self.ax = 0
        self.cost_scale = 100.0
        self.titanium_found = False
        self.axionite_found = False
        self.foundry_prev_placed = False
        self.foundry_curr_placed = False
        self.splitter_for_foundry = False
        self.foundry_placed_round: int = -1
        
        self.environment_map: EnvironmentMap | None = None
        self.seek_planner: DStarLite | None = None
        self.seek_planner_goal: tuple[int, int] | None = None
        self.return_planner: DStarLite | None = None
        self.target_pos: Position | None = None
        self.seek_target_is_ore = False
        self.blacklisted_ores: set[tuple[int, int]] = set()
        self.blacklisted_seek_targets: set[tuple[int, int]] = set()
        self.seek_stall_target: Position | None = None
        self.seek_target_turns: int = 0
        self.edge_cycle_index = 0
        self.spawn_pos: Position | None = None
        self.harvester_pos: Position | None = None
        self.just_placed = False
        self.bridge_jump_target: Position | None = None
        self.bridge_target_planner: DStarLite | None = None
        # carry-forward: direction to move on the next _build_return_step call;
        # set by the first-connector step, diagonal splits, and post-bridge conveyor.
        self.return_next_dir: Direction | None = None
        self.post_bridge_conveyor = False
        self.return_bridge_fail_counts = {}
        self.heal_target: Position | None = None
        self.patrol_turns: int = 0
        self.patrol_target: Position | None = None
        self.patrol_going_out: bool = True
        self.patrol_tip: Position | None = None

        self.placing_ore_pos: Position | None = None
        self.placing_exit_pos: Position | None = None
        self.placing_sides_pending: list[Direction] = []
        self.placing_phase: str = _PLACING_STEP_ON
        self.placing_ring_turns: int = 0
        self.placing_is_titanium: bool = False

        self.defend_prev_state: HarvestState | None = None
        self.defend_enemy_id: int | None = None
        self.defend_target_tile: Position | None = None
        self.defend_gunner_pos: Position | None = None
        self.defend_orig_conveyor_dir: Direction | None = None
        self.enemy_tile_hp: dict[tuple[int, int], int] = {}

        self.heal_prev_state: HarvestState | None = None
        self.heal_interrupt_target: Position | None = None

        self.harvesters_placed = 0
        self.titanium_harvesters_placed = 0
        self.axionite_harvesters_placed = 0
        self.returning_from_axionite = False

        self.broadcaster = Broadcaster()
        self._symmetry_broadcasted = False
        self._core_broadcasted = False
        self._enemy_core_broadcasted = False

    def _check_for_foundry(self, c: Controller):
        """Identify visible allied foundries without guessing from cost scale."""
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == c.get_team() and c.get_entity_type(bid) == EntityType.FOUNDRY:
                if not self.foundry_prev_placed:
                    pos = c.get_position(bid)
                    print(
                        f"[foundry_join] id={c.get_id()} r={c.get_current_round()} "
                        f"seen_allied_foundry pos=({pos.x},{pos.y})",
                        file=sys.stderr,
                    )
                self.foundry_prev_placed = True
                break

    def _can_trigger_foundry(self, c: Controller) -> bool:
        return False

    def _axionite_unlocked(self, c: Controller) -> bool:
        return (
            self.titanium_harvesters_placed >= _TITANIUM_HARVESTER_TARGET
            or c.get_current_round() >= _AXIONITE_UNLOCK_ROUND
        )

    def _clear_if_road(self, c: Controller, pos: Position):
        """Safely clear road tiles"""
        build_id = c.get_tile_building_id(pos)
        if (
            build_id is not None
            and c.get_entity_type(build_id) == EntityType.ROAD
            and c.can_destroy(pos)
        ):
            c.destroy(pos)

    def _advance(self, c: Controller, move_dir):
        """Move toward target and build a road on the tile stepped onto"""
        if move_dir is None:
            return

        move_pos = self.current_pos.add(move_dir)
        build_id = c.get_tile_building_id(move_pos)
        if build_id is not None and c.get_entity_type(build_id) == EntityType.MARKER and c.can_destroy(move_pos):
            c.destroy(move_pos)

        if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
            c.build_road(move_pos)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _is_valid_titanium_target(self, c: Controller, ore_pos: Position) -> bool:
        if not is_ore_titanium(c, ore_pos):
            return False

        build_id = c.get_tile_building_id(ore_pos)
        if build_id is None:
            return True
        return c.get_entity_type(build_id) not in {EntityType.HARVESTER, EntityType.GUNNER}

    def _is_valid_axionite_target(self, c: Controller, ore_pos: Position) -> bool:
        if not is_ore_axionite(c, ore_pos):
            return False

        build_id = c.get_tile_building_id(ore_pos)
        if build_id is None:
            return True
        return c.get_entity_type(build_id) not in {EntityType.HARVESTER, EntityType.GUNNER}

    def _is_valid_ore_target(self, c: Controller, ore_pos: Position) -> bool:
        if not self._axionite_unlocked(c):
            return self._is_valid_titanium_target(c, ore_pos)
        return self._is_valid_axionite_target(c, ore_pos)

    def _try_build_harvester(self, c: Controller) -> bool:
        """Detect a valid adjacent ore and enter the placing-harvester sequence."""
        ore_pos, is_titanium = self._pick_adjacent_ore(c)
        if ore_pos is None:
            return False

        self.placing_ore_pos = ore_pos
        self.placing_exit_pos = self.current_pos
        self.placing_is_titanium = is_titanium
        self.placing_phase = _PLACING_STEP_ON
        self.placing_sides_pending = list(DIRECTIONS_4)
        self.placing_ring_turns = 0
        self.state = HarvestState.PLACING_HARVESTER
        # Kick off step_on this turn so we don't lose a tick on the transition.
        _placing_harvester_state(self, c)
        return True

    def _pick_adjacent_ore(self, c: Controller) -> tuple[Position | None, bool]:
        if not self._axionite_unlocked(c):
            for direction in DIRECTIONS_4:
                ore_pos = self.current_pos.add(direction)
                if self._is_valid_titanium_target(c, ore_pos):
                    return ore_pos, True

        if (
            self._axionite_unlocked(c)
        ):
            for direction in DIRECTIONS_4:
                ore_pos = self.current_pos.add(direction)
                if self._is_valid_axionite_target(c, ore_pos):
                    return ore_pos, False

        return None, False

    def _draw_debug(self, c: Controller):
        """Draw state-based dot and target line for debugging"""
        state_colors = {
            HarvestState.SEEK: (0, 0, 255),
            HarvestState.PLACING_HARVESTER: (200, 0, 200),
            HarvestState.RETURN: (255, 165, 0),
            HarvestState.PLACING_FOUNDRY: (255, 255, 0),
            HarvestState.DEFEND: (255, 0, 0),
            HarvestState.PATROL: (0, 255, 200),
            HarvestState.HEAL: (0, 255, 80),
        }
        r, g, b = state_colors.get(self.state, (255, 255, 255))
        c.draw_indicator_dot(self.current_pos, r, g, b)

        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, r, g, b)
        elif self.state == HarvestState.RETURN and self.current_pos != self.core_pos:
            c.draw_indicator_line(self.current_pos, self.core_pos, 255, 255, 0)

    def _placing_foundry(self, c: Controller):
        _foundry_state(self, c)

    def _placing_harvester(self, c: Controller):
        _placing_harvester_state(self, c)

    def _defend(self, c: Controller):
        _defend_state(self, c)

    def _heal(self, c: Controller):
        _heal_state(self, c)

    def _seek(self, c: Controller):
        _seek_state(self, c)

    def _patrol(self, c: Controller):
        _patrol_state(self, c)

    def _return(self, c: Controller):
        """Lay conveyors back to the core"""
        # If we're already on/adjacent to core, RETURN is complete.
        if reached_core(self.current_pos, self.core_pos) and self.bridge_jump_target is None:
            if self._can_trigger_foundry(c):
                self.state = HarvestState.PLACING_FOUNDRY
            elif self.harvesters_placed >= 1:
                self.patrol_tip = self.harvester_pos  # save before it's cleared
                self.patrol_turns = 0
                self.patrol_target = None
                self.patrol_going_out = True
                self.state = HarvestState.PATROL
            else:
                self.state = HarvestState.SEEK
            self.target_pos = None
            self.seek_target_is_ore = False
            self.harvester_pos = None
            self.returning_from_axionite = False
            _reset_return_state(self)
            return

        # Standing on an enemy walkable tile: fire until it's destroyed, then
        # resume the normal flow (post_bridge_conveyor will rebuild the chain).
        if _attack_enemy_under_bot(self, c):
            return

        if _handle_post_bridge_conveyor(self, c):
            return

        _build_return_step(self, c)

    def run(self, c: Controller):
        if _PROFILE_ENABLED:
            global _PROFILE_CALLS
            _PROFILER.enable()
        self.current_pos = c.get_position()
        if self.spawn_pos is None:
            self.spawn_pos = self.current_pos
        self.ti, self.ax = c.get_global_resources()
        if self.ax > 0:
            self.axionite_found = True
        if self.environment_map is None:
            self.environment_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        self.environment_map.update(c)
        self._check_for_foundry(c)

        if not self.environment_map.symmetry_resolved:
            raw = BuilderBotMessages.read_nearby_symmetry(c)
            if raw is not None:
                try:
                    self.environment_map.force_symmetry(Symmetry(raw))
                except ValueError:
                    pass

        if self.environment_map.symmetry is not None:
            if not self._symmetry_broadcasted:
                self.broadcaster.add_broadcast(
                    BuilderBotMessages.encode_symmetry(self.environment_map.symmetry.value)
                )
                self._symmetry_broadcasted = True
            if not self._core_broadcasted:
                self.broadcaster.add_broadcast(
                    BuilderBotMessages.encode_core_position(self.core_pos)
                )
                self._core_broadcasted = True
            if not self._enemy_core_broadcasted:
                enemy_core = self.environment_map.enemy_core_centre(self.core_pos)
                if enemy_core is not None:
                    self.broadcaster.add_broadcast(
                        BuilderBotMessages.encode_enemy_core_position(enemy_core)
                    )
                    self._enemy_core_broadcasted = True

        if self.state is not HarvestState.DEFEND:
            _try_enter_defend(self, c)

        if self.state not in (HarvestState.DEFEND, HarvestState.HEAL, HarvestState.PLACING_HARVESTER, HarvestState.PLACING_FOUNDRY):
            _try_enter_heal(self, c)

        match self.state:
            case HarvestState.SEEK:
                self._seek(c)
            case HarvestState.PLACING_HARVESTER:
                self._placing_harvester(c)
            case HarvestState.RETURN:
                self._return(c)
            case HarvestState.PLACING_FOUNDRY:
                self._placing_foundry(c)
            case HarvestState.DEFEND:
                self._defend(c)
            case HarvestState.PATROL:
                self._patrol(c)
            case HarvestState.HEAL:
                self._heal(c)

        self.broadcaster.run(c)

        self._draw_debug(c)
        self._log_turn_state(c)
        if _PROFILE_ENABLED:
            _PROFILER.disable()
            _PROFILE_CALLS += 1
            if _PROFILE_CALLS % _PROFILE_DUMP_EVERY == 0:
                _PROFILER.dump_stats(_PROFILE_PATH)

    def _log_turn_state(self, c: Controller):
        under_id = c.get_tile_building_id(self.current_pos)
        under = "-"
        if under_id is not None:
            et = c.get_entity_type(under_id)
            team_tag = "us" if c.get_team(under_id) == c.get_team() else "enemy"
            under = f"{et.name}({team_tag})"
            if et in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE):
                under += f",dir={c.get_direction(under_id).name if et != EntityType.BRIDGE else c.get_bridge_target(under_id)}"
        print(
            f"[harv {c.get_id()}] r={c.get_current_round()} "
            f"pos=({self.current_pos.x},{self.current_pos.y}) "
            f"state={self.state.value} "
            f"acd={c.get_action_cooldown()} mcd={c.get_move_cooldown()} "
            f"under={under} "
            f"next_dir={self.return_next_dir.name if self.return_next_dir else '-'} "
            f"bridge_target={(self.bridge_jump_target.x, self.bridge_jump_target.y) if self.bridge_jump_target else '-'} "
            f"post_bridge={self.post_bridge_conveyor} "
            f"just_placed={self.just_placed} "
            f"ax_return={self.returning_from_axionite} "
            f"foundry_seen={self.foundry_prev_placed}"
        )
