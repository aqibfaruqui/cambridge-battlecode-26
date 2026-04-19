import cProfile
import os
import uuid
from enum import Enum

from cambc import Controller, Direction, EntityType, Environment, Position
from utils.board import is_ore_axionite, is_ore_titanium
from utils.harvester_states.foundry import _placing_foundry as _foundry_state
from utils.harvester_states.return_to_core import (
    _build_first_connector,
    _build_return_step,
    _ensure_post_bridge_conveyor,
    _harvester_attached_to_core,
    _handle_pending_return_bridge,
    _reset_return_state,
)
from utils.harvester_states.seek import (
    _seek as _seek_state,
)
from utils.map_memory import MapMemory
from utils.movement import DIRECTIONS_4, reached_core
from utils.pathfinding import Pathfinding
from utils.raw_map_representation import EnvironmentMap
from utils.d_star import DStarLite


_PROFILER = cProfile.Profile()
_PROFILE_DIR = "/tmp/harvester_profiles"
_PROFILE_ID = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
_PROFILE_PATH = os.path.join(_PROFILE_DIR, f"harv_{_PROFILE_ID}.pstats")
_PROFILE_CALLS = 0
_PROFILE_DUMP_EVERY = 100
os.makedirs(_PROFILE_DIR, exist_ok=True)

class HarvestState(Enum):
    __slots__ = ()

    SEEK = "seek"
    RETURN = "return"
    PLACING_FOUNDRY = "placing_foundry"


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

        self.memory = MapMemory()
        self.memory.set_core(core_pos)
        self.environment_map: EnvironmentMap | None = None
        self.pathfinder = Pathfinding()
        self.pathfinder.set_memory(self.memory)
        self.seek_planner: DStarLite | None = None
        self.seek_planner_goal: tuple[int, int] | None = None
        self.return_planner: DStarLite | None = None

        self.target_pos: Position | None = None
        self.seek_target_is_ore = False
        self.blacklisted_ores: set[tuple[int, int]] = set()
        self.blacklisted_seek_targets: set[tuple[int, int]] = set()
        self.seek_unreachable_counts: dict[tuple[int, int], int] = {}
        self.edge_cycle_index = 0
        self.network_reach_round = -1
        self.network_reach_dirty = True
        self.reachable_to_core: set[tuple[int, int]] | None = None
        self.harvester_pos: Position | None = None
        self.just_placed = False
        self.bridge_from: Position | None = None
        self.return_next_dir: Direction | None = None
        self.post_bridge_conveyor = False
        self.return_bridge_fail_counts = {}

    def _check_for_foundry(self, c: Controller):
        """Identify if another builder has built a foundry"""
        new_cost_scale = c.get_scale_percent()
        if new_cost_scale >= self.cost_scale + 100.0:
            self.foundry_prev_placed = True
        self.cost_scale = new_cost_scale

    def _can_trigger_foundry(self, c: Controller) -> bool:
        foundry_cost = c.get_foundry_cost()[0]
        return (
            self.titanium_found
            and self.axionite_found
            and self.ti >= foundry_cost
            and not self.foundry_prev_placed
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
        return c.get_entity_type(build_id) != EntityType.HARVESTER

    def _is_valid_axionite_target(self, c: Controller, ore_pos: Position) -> bool:
        if not is_ore_axionite(c, ore_pos):
            return False

        build_id = c.get_tile_building_id(ore_pos)
        if build_id is None:
            return True
        return c.get_entity_type(build_id) != EntityType.HARVESTER

    def _is_valid_ore_target(self, c: Controller, ore_pos: Position) -> bool:
        return self._is_valid_titanium_target(c, ore_pos) or (
            self.titanium_found
            and not self.axionite_found
            and not self.foundry_prev_placed
            and self._is_valid_axionite_target(c, ore_pos)
        )

    def _try_build_harvester(self, c: Controller) -> bool:
        """Check cardinal directions and place a harvester (titanium first, then axionite)"""
        for direction in DIRECTIONS_4:
            ore_pos = self.current_pos.add(direction)
            if not self._is_valid_titanium_target(c, ore_pos):
                continue

            self._clear_if_road(c, ore_pos)
            if not c.can_build_harvester(ore_pos):
                continue

            c.build_harvester(ore_pos)
            self.titanium_found = True
            self.blacklisted_ores.discard((ore_pos.x, ore_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
            self.harvester_pos = ore_pos
            self.just_placed = True
            _reset_return_state(self)
            self.state = HarvestState.RETURN
            return True

        for direction in DIRECTIONS_4:
            ore_pos = self.current_pos.add(direction)
            if not (
                self.titanium_found
                and not self.axionite_found
                and not self.foundry_prev_placed
                and self._is_valid_axionite_target(c, ore_pos)
            ):
                continue

            self._clear_if_road(c, ore_pos)
            if not c.can_build_harvester(ore_pos):
                continue

            c.build_harvester(ore_pos)
            self.axionite_found = True
            self.target_pos = None
            self.seek_target_is_ore = False
            self.harvester_pos = ore_pos
            self.just_placed = True
            _reset_return_state(self)
            self.state = HarvestState.RETURN
            return True

        return False

    def _draw_debug(self, c: Controller):
        """Draw state-based dot and target line for debugging"""
        state_colors = {
            HarvestState.SEEK: (0, 0, 255),
            HarvestState.RETURN: (255, 165, 0),
            HarvestState.PLACING_FOUNDRY: (255, 255, 0),
        }
        r, g, b = state_colors.get(self.state, (255, 255, 255))
        c.draw_indicator_dot(self.current_pos, r, g, b)

        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, r, g, b)
        elif self.state == HarvestState.RETURN and self.current_pos != self.core_pos:
            c.draw_indicator_line(self.current_pos, self.core_pos, 255, 255, 0)

    def _placing_foundry(self, c: Controller):
        _foundry_state(self, c)

    def _seek(self, c: Controller):
        _seek_state(self, c)

    def _return(self, c: Controller):
        """Lay conveyors back to the core"""
        # If we're already on/adjacent to core, RETURN is complete.
        if reached_core(self.current_pos, self.core_pos):
            self.state = HarvestState.PLACING_FOUNDRY if self._can_trigger_foundry(c) else HarvestState.SEEK
            self.target_pos = None
            self.seek_target_is_ore = False
            self.harvester_pos = None
            _reset_return_state(self)
            return

        if self.just_placed:
            if _build_first_connector(self, c):
                self.just_placed = False
            return

        if _harvester_attached_to_core(self, c):
            self.state = HarvestState.PLACING_FOUNDRY if self._can_trigger_foundry(c) else HarvestState.SEEK
            self.target_pos = None
            self.seek_target_is_ore = False
            self.harvester_pos = None
            _reset_return_state(self)
            return

        if self.bridge_from is not None:
            _handle_pending_return_bridge(self, c)
            return

        if self.post_bridge_conveyor:
            _ensure_post_bridge_conveyor(self, c)
            return

        _build_return_step(self, c)

    def run(self, c: Controller):
        global _PROFILE_CALLS
        _PROFILER.enable()
        self.current_pos = c.get_position()
        self.ti, self.ax = c.get_global_resources()
        if self.environment_map is None:
            self.environment_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        self.environment_map.update(c)
        self._check_for_foundry(c)

        match self.state:
            case HarvestState.SEEK:
                self._seek(c)
            case HarvestState.RETURN:
                self._return(c)
            case HarvestState.PLACING_FOUNDRY:
                self._placing_foundry(c)

        self._draw_debug(c)
        _PROFILER.disable()
        _PROFILE_CALLS += 1
        if _PROFILE_CALLS % _PROFILE_DUMP_EVERY == 0:
            _PROFILER.dump_stats(_PROFILE_PATH)