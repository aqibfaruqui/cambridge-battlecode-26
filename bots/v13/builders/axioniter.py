import os
import uuid
from enum import Enum

from cambc import Controller, Direction, EntityType, Environment, Position
from utils.map.board import is_ore_axionite
from utils.axioniter_states.return_to_core import (
    _attack_enemy_under_bot,
    _build_return_step,
    _clear_bridge_walk_state,
    _handle_foundry_outbound,
    _handle_post_bridge_conveyor,
    _reset_return_state,
    _try_chain_shortcut,
)
from utils.axioniter_states.seek import (
    _seek as _seek_state,
)
from utils.axioniter_states.patrol import (
    _patrol as _patrol_state,
)
from utils.axioniter_states.placing_harvester import (
    STEP_ON as _PLACING_STEP_ON,
    _placing_harvester as _placing_harvester_state,
)
from utils.axioniter_states.defend import (
    _defend as _defend_state,
)
from utils.axioniter_states.heal import (
    _heal as _heal_state,
    _try_enter_heal,
)
from utils.pathfinding.movement import DIRECTIONS_4
from utils.map.raw_map_representation import EnvironmentMap, Symmetry
from utils.pathfinding.d_star import DStarLite
from utils.comms.broadcaster import Broadcaster
from utils.comms.for_builder_bot import BuilderBotMessages
from utils.healing import try_heal_nearby_bot, try_heal_nearby_building


# Profiling is only available locally. AWS runners ship a stripped-down CPython
# without _lsprof (the C extension cProfile depends on), so we probe for it
# capability-style rather than sniffing env vars (which the sandbox may hide).
try:
    import cProfile

    _PROFILE_ENABLED = os.environ.get("HARVESTER_PROFILE") == "1"
    if _PROFILE_ENABLED:
        _PROFILER = cProfile.Profile()
        _PROFILE_DIR = "/tmp/harvester_profiles"
        _PROFILE_ID = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        _PROFILE_PATH = os.path.join(_PROFILE_DIR, f"harv_{_PROFILE_ID}.pstats")
        _PROFILE_CALLS = 0
        _PROFILE_DUMP_EVERY = 100
        os.makedirs(_PROFILE_DIR, exist_ok=True)
except ImportError:
    _PROFILE_ENABLED = False


class AxioniterState(Enum):
    __slots__ = ()

    SEEK = "seek"
    PLACING_HARVESTER = "placing_harvester"
    RETURN = "return"
    DEFEND = "defend"
    PATROL = "patrol"
    HEAL = "heal"


_FOUNDRY_SCALE_JUMP = 45.0


class Axioniter:
    def __init__(self, core_pos: Position):
        self.state = AxioniterState.SEEK
        self.core_pos = core_pos
        self.current_pos = Position(0, 0)

        self.ti = 0
        self.ax = 0
        self.cost_scale = 100.0
        self._scale_initialized = False
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
        self.return_planner_goal: tuple[int, int] | None = None
        self.return_target_pos: Position | None = None
        self.return_harvester_pos: Position | None = None
        self.outbound_foundry_pos: Position | None = None
        self.outbound_start_pos: Position | None = None
        self.outbound_started = False
        self.team_titanium_harvesters: set[tuple[int, int]] = set()
        self.target_pos: Position | None = None
        self.seek_target_is_ore = False
        self.blacklisted_ores: set[tuple[int, int]] = set()
        self.blacklisted_seek_targets: set[tuple[int, int]] = set()
        self.seek_stall_target: Position | None = None
        self.seek_target_turns: int = 0
        self.edge_cycle_index = 0
        self.bot_id: int = -1
        self.spawn_pos: Position | None = None
        self.harvester_pos: Position | None = None
        self.just_placed = False
        self.bridge_jump_target: Position | None = None
        self.bridge_target_planner: DStarLite | None = None
        # carry-forward: direction to move on the next _build_return_step call;
        # set by the first-connector step, diagonal splits, and post-bridge conveyor.
        self.return_next_dir: Direction | None = None
        self.return_chain_cursor: Position | None = None
        self.post_bridge_conveyor = False
        self.return_bridge_fail_counts = {}
        self.failed_bridge_targets: set[tuple[int, int]] = set()
        self.chain_memory: dict[tuple[int, int], dict] = {}
        self.heal_target: Position | None = None
        self.patrol_turns: int = 0
        self.patrol_target: Position | None = None
        self.patrol_going_out: bool = True
        self.patrol_tip: Position | None = None
        self.patrol_inner: Position | None = None

        self.placing_ore_pos: Position | None = None
        self.placing_exit_pos: Position | None = None
        self.placing_sides_pending: list[Direction] = []
        self.placing_phase: str = _PLACING_STEP_ON
        self.placing_ring_turns: int = 0
        self.placing_is_titanium: bool = False

        self.defend_prev_state: AxioniterState | None = None
        self.defend_target_tile: Position | None = None
        self.defend_cleared_tiles: list[tuple[int, int, Direction]] = []
        self.defend_enemy_id: int | None = None
        self.defend_gunner_pos: Position | None = None
        self.defend_orig_conveyor_dir: Direction | None = None
        self.enemy_tile_hp: dict[tuple[int, int], int] = {}

        self.heal_prev_state: AxioniterState | None = None
        self.heal_interrupt_target: Position | None = None
        self.heal_idle_turns: int = 0

        self.harvesters_placed = 0
        self.titanium_harvesters_placed = 0
        self.axionite_harvesters_placed = 0
        self.returning_from_axionite = False

        self.broadcaster = Broadcaster()
        self._symmetry_broadcasted = False
        self._core_broadcasted = False
        self._enemy_core_broadcasted = False

    def _mark_foundry_seen(
        self, c: Controller, reason: str, pos: Position | None = None
    ) -> None:
        if not self.foundry_prev_placed:
            suffix = "" if pos is None else f" pos=({pos.x},{pos.y})"
            print(
                f"[foundry_join] id={c.get_id()} r={c.get_current_round()} "
                f"{reason}{suffix}",
            )
        self.foundry_prev_placed = True
        self.returning_from_axionite = False
        if (
            self.target_pos is not None
            and self.seek_target_is_ore
            and c.is_in_vision(self.target_pos)
        ):
            if is_ore_axionite(c, self.target_pos):
                self.blacklisted_ores.discard((self.target_pos.x, self.target_pos.y))
                self.target_pos = None
                self.seek_target_is_ore = False

    def _check_for_foundry(self, c: Controller, nearby_buildings=None):
        """Identify the one-foundry cap from vision or a single-turn scale jump."""
        scale = c.get_scale_percent()
        if self._scale_initialized and scale - self.cost_scale >= _FOUNDRY_SCALE_JUMP:
            self._mark_foundry_seen(
                c, f"scale_jump_{self.cost_scale:.1f}_to_{scale:.1f}"
            )
        self.cost_scale = scale
        self._scale_initialized = True

        if self.foundry_prev_placed:
            return

        if nearby_buildings is None:
            nearby_buildings = c.get_nearby_buildings()
        team = c.get_team()
        for bid in nearby_buildings:
            if c.get_team(bid) == team and c.get_entity_type(bid) == EntityType.FOUNDRY:
                self._mark_foundry_seen(c, "seen_allied_foundry", c.get_position(bid))
                break

    def _axionite_unlocked(self, c: Controller) -> bool:
        return True

    def _record_seen_team_harvesters(
        self, c: Controller, nearby_buildings=None
    ) -> None:
        if nearby_buildings is None:
            nearby_buildings = c.get_nearby_buildings()
        team = c.get_team()
        for bid in nearby_buildings:
            if c.get_team(bid) != team:
                continue
            if c.get_entity_type(bid) != EntityType.HARVESTER:
                continue
            pos = c.get_position(bid)
            if c.get_tile_env(pos) == Environment.ORE_TITANIUM:
                self.team_titanium_harvesters.add((pos.x, pos.y))

    def _valid_return_adjacent(self, c: Controller, pos: Position) -> bool:
        if not (0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()):
            return False

        if c.is_in_vision(pos):
            bot_id = c.get_tile_builder_bot_id(pos)
            if bot_id is not None and bot_id != c.get_id():
                return False
            bid = c.get_tile_building_id(pos)
            if bid is not None:
                etype = c.get_entity_type(bid)
                if etype == EntityType.MARKER:
                    return True
                if c.get_team(bid) != c.get_team():
                    return False
                return etype in {
                    EntityType.ROAD,
                    EntityType.CONVEYOR,
                    EntityType.ARMOURED_CONVEYOR,
                    EntityType.BRIDGE,
                    EntityType.SPLITTER,
                    EntityType.FOUNDRY,
                }
            return c.get_tile_env(pos) == Environment.EMPTY

        env = self.environment_map
        return env is None or env.is_seek_candidate(pos.x, pos.y)

    def _refresh_return_target(self, c: Controller) -> None:
        if not self.team_titanium_harvesters:
            self.return_target_pos = None
            self.return_harvester_pos = None
            self.return_planner = None
            self.return_planner_goal = None
            return

        ordered = sorted(
            (Position(x, y) for x, y in self.team_titanium_harvesters),
            key=lambda p: self.current_pos.distance_squared(p),
        )
        for harvester_pos in ordered:
            candidates = []
            for direction in DIRECTIONS_4:
                adj = harvester_pos.add(direction)
                if self._valid_return_adjacent(c, adj):
                    candidates.append(adj)
            if not candidates:
                continue
            candidates.sort(key=lambda p: self.current_pos.distance_squared(p))
            next_target = candidates[0]
            old_goal = (
                None
                if self.return_target_pos is None
                else (
                    self.return_target_pos.x,
                    self.return_target_pos.y,
                )
            )
            new_goal = (next_target.x, next_target.y)
            self.return_target_pos = next_target
            self.return_harvester_pos = harvester_pos
            if old_goal != new_goal:
                self.return_planner = None
                self.return_planner_goal = None
            return

        self.return_target_pos = None
        self.return_harvester_pos = None
        self.return_planner = None
        self.return_planner_goal = None

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
        if (
            build_id is not None
            and c.get_entity_type(build_id) == EntityType.MARKER
            and c.can_destroy(move_pos)
        ):
            c.destroy(move_pos)

        if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
            c.build_road(move_pos)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _is_valid_axionite_target(self, c: Controller, ore_pos: Position) -> bool:
        if not is_ore_axionite(c, ore_pos):
            return False

        build_id = c.get_tile_building_id(ore_pos)
        if build_id is None:
            return True
        return c.get_entity_type(build_id) not in {
            EntityType.HARVESTER,
            EntityType.GUNNER,
        }

    def _is_valid_ore_target(self, c: Controller, ore_pos: Position) -> bool:
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
        self.state = AxioniterState.PLACING_HARVESTER
        # Kick off step_on this turn so we don't lose a tick on the transition.
        _placing_harvester_state(self, c)
        return True

    def _pick_adjacent_ore(self, c: Controller) -> tuple[Position | None, bool]:
        for direction in DIRECTIONS_4:
            ore_pos = self.current_pos.add(direction)
            if self._is_valid_axionite_target(c, ore_pos):
                return ore_pos, False

        return None, False

    def _draw_debug(self, c: Controller):
        """Draw state-based dot and target line for debugging"""
        state_colors = {
            AxioniterState.SEEK: (0, 0, 255),
            AxioniterState.PLACING_HARVESTER: (200, 0, 200),
            AxioniterState.RETURN: (255, 165, 0),
            AxioniterState.DEFEND: (255, 0, 0),
            AxioniterState.PATROL: (0, 255, 200),
            AxioniterState.HEAL: (0, 255, 80),
        }
        r, g, b = state_colors.get(self.state, (255, 255, 255))
        c.draw_indicator_dot(self.current_pos, r, g, b)

        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, r, g, b)
        elif self.state == AxioniterState.RETURN and self.current_pos != self.core_pos:
            c.draw_indicator_line(self.current_pos, self.core_pos, 255, 255, 0)

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
        """Lay conveyors back to a tile adjacent to a known titanium harvester."""
        if _handle_foundry_outbound(self, c):
            return

        self._refresh_return_target(c)
        if self.return_target_pos is None:
            self.returning_from_axionite = False
            self.harvester_pos = None
            self.target_pos = None
            self.seek_target_is_ore = False
            self.state = AxioniterState.SEEK
            _reset_return_state(self)
            return

        if (
            self.bridge_jump_target is not None
            and self.current_pos.distance_squared(self.bridge_jump_target) == 0
        ):
            _clear_bridge_walk_state(self)
            self.post_bridge_conveyor = True

        if _try_chain_shortcut(self, c):
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
        if self.bot_id == -1:
            self.bot_id = c.get_id()
        if self.spawn_pos is None:
            self.spawn_pos = self.current_pos
        self.ti, self.ax = c.get_global_resources()
        if self.ax > 0:
            self.axionite_found = True
        if self.environment_map is None:
            self.environment_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        nearby_tiles = c.get_nearby_tiles()
        nearby_buildings = c.get_nearby_buildings()
        self.environment_map.update(c, nearby_tiles, nearby_buildings)
        self._record_seen_team_harvesters(c, nearby_buildings)
        self._check_for_foundry(c, nearby_buildings)

        if not self.environment_map.symmetry_resolved:
            raw = BuilderBotMessages.read_nearby_symmetry(c, nearby_buildings)
            if raw is not None:
                try:
                    self.environment_map.force_symmetry(Symmetry(raw))
                except ValueError:
                    pass

        if self.environment_map.symmetry is not None:
            if not self._symmetry_broadcasted:
                self.broadcaster.add_broadcast(
                    BuilderBotMessages.encode_symmetry(
                        self.environment_map.symmetry.value
                    )
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

        try_heal_nearby_bot(c, self.current_pos)
        try_heal_nearby_building(c, self.current_pos)

        if self.state not in (
            AxioniterState.DEFEND,
            AxioniterState.HEAL,
            AxioniterState.PLACING_HARVESTER,
        ):
            _try_enter_heal(self, c)

        match self.state:
            case AxioniterState.SEEK:
                self._seek(c)
            case AxioniterState.PLACING_HARVESTER:
                self._placing_harvester(c)
            case AxioniterState.RETURN:
                self._return(c)
            case AxioniterState.DEFEND:
                self._defend(c)
            case AxioniterState.PATROL:
                self._patrol(c)
            case AxioniterState.HEAL:
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
        def _fmt_pos(pos: Position | None) -> str:
            return "-" if pos is None else f"({pos.x},{pos.y})"

        def _fmt_symmetry() -> str:
            env = self.environment_map
            if env is None:
                return "-"
            if env.symmetry is None:
                return "unresolved"
            return env.symmetry.name

        under_id = c.get_tile_building_id(self.current_pos)
        under = "-"
        if under_id is not None:
            et = c.get_entity_type(under_id)
            team_tag = "us" if c.get_team(under_id) == c.get_team() else "enemy"
            under = f"{et.name}({team_tag})"
            if et in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE):
                under_dir = (
                    c.get_direction(under_id).name
                    if et != EntityType.BRIDGE
                    else _fmt_pos(c.get_bridge_target(under_id))
                )
                under += f",dir={under_dir}"

        target_kind = "ore" if self.seek_target_is_ore else "explore"
        return_mode = "normal"
        if self.bridge_jump_target is not None:
            return_mode = "bridge_walk"
        elif self.post_bridge_conveyor:
            return_mode = "post_bridge"
        elif self.return_chain_cursor is not None:
            return_mode = "remote_chain"
        print(
            f"[axioniter {c.get_id()}] r={c.get_current_round()} "
            f"state={self.state.value} "
            f"acd={c.get_action_cooldown()} mcd={c.get_move_cooldown()} "
            f"target={_fmt_pos(self.target_pos)} target_kind={target_kind} "
            f"target_turns={self.seek_target_turns} "
            f"under={under} "
            f"harv_pos={_fmt_pos(self.harvester_pos)} "
            f"return_mode={return_mode} "
            f"next_dir={self.return_next_dir.name if self.return_next_dir else '-'} "
            f"bridge_target={_fmt_pos(self.bridge_jump_target)} "
            f"bridge_fails={len(self.return_bridge_fail_counts)} failed_bridges={len(self.failed_bridge_targets)} "
            f"just_placed={self.just_placed} "
            f"ax_return={self.returning_from_axionite} "
            f"heal_target={_fmt_pos(self.heal_target)} defend_target={_fmt_pos(self.defend_target_tile)} "
            f"blacklist=ore:{len(self.blacklisted_ores)},seek:{len(self.blacklisted_seek_targets)} "
            f"foundry_seen={self.foundry_prev_placed} scale={self.cost_scale:.1f} "
            f"cpu={c.get_cpu_time_elapsed()}us"
        )
