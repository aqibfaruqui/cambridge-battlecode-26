from enum import Enum
from cambc import Controller, Direction, EntityType, Environment, Position
from utils.movement import (
    DIRECTIONS_4,
    DIAGONALS,
    random_direction_4,
    bug_nav,
    on_map,
)
from utils.board import (
    action_radius,
    is_wall,
    is_tile_conveyor,
    is_tile_foundry,
    is_tile_splitter,
    replace_with_conveyor,
    is_ore_titanium,
    is_ore_axionite,
    nearby_titanium,
    nearby_ore,
    on_core_border,
)


class HarvestState(Enum):
    __slots__ = ()

    BUILDING_OUTWARD = "building_outward"
    SEARCHING_ORES = "searching_ores"
    PLACING_FOUNDRY = "placing_foundry"


class Harvester:
    def __init__(self, core_pos: Position):
        self.state = HarvestState.BUILDING_OUTWARD
        self.core_pos = core_pos
        self.current_pos = None
        self.ti = 0
        self.ax = 0
        self.bridge_target = None
        self.foundry_prev_placed = False
        self.foundry_curr_placed = False
        self.splitter_for_foundry = False
        self.titanium_found = False
        self.axionite_found = False
        self.cost_scale = 100.0
        self._bug_follow_state: dict | None = None
        self.target_pos: Position | None = None

    def _build_and_move(self, c: Controller, pos: Position, move_dir: Direction):
        """Place backwards conveyor/bridge in movement direction and move to it"""
        if move_dir == Direction.CENTRE:
            move_dir = random_direction_4()

        bridge_target = None

        if move_dir in DIAGONALS:
            left_pos = pos.add(move_dir.rotate_left())
            right_pos = pos.add(move_dir.rotate_right())
            if is_wall(c, left_pos) and is_wall(c, right_pos):
                bridge_target = pos
            else:
                move_dir = move_dir.rotate_left()

        next_pos = pos.add(move_dir)

        if move_dir in DIAGONALS:
            bridge_target = self._handle_diagonal_step(c, pos, move_dir)
        elif self.bridge_target:
            self._handle_pending_bridge(c, pos, move_dir)
            bridge_target = None
        else:
            self._handle_conveyor_step(c, next_pos, move_dir)

        self.bridge_target = bridge_target

    def _check_for_foundry(self, c: Controller):
        """Identify if another builder has built a foundry"""
        new_cost_scale = c.get_scale_percent()
        if new_cost_scale >= self.cost_scale + 100.0:
            self.foundry_prev_placed = True
        self.cost_scale = new_cost_scale

    def _clear_if_road(self, c: Controller, pos: Position):
        """Safely clear road tiles"""
        build_id = c.get_tile_building_id(pos)
        if (
            build_id is not None
            and c.get_entity_type(build_id) == EntityType.ROAD
            and c.can_destroy(pos)
        ):
            c.destroy(pos)

    def _handle_conveyor_step(
        self, c: Controller, move_pos: Position, move_dir: Direction
    ):
        """Move cardinally via conveyor (placed backwards)"""
        conveyor_dir = move_dir.opposite()

        if not is_ore_titanium(c, move_pos):
            self._clear_if_road(c, move_pos)
            if c.can_build_conveyor(move_pos, conveyor_dir):
                c.build_conveyor(move_pos, conveyor_dir)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _handle_diagonal_step(
        self, c: Controller, pos: Position, move_dir: Direction
    ) -> Position:
        """Move diagonally via road (to place backwards bridge later)"""
        move_pos = pos.add(move_dir)

        if c.get_tile_env(move_pos) == Environment.EMPTY:
            if c.can_build_road(move_pos):
                c.build_road(move_pos)

        if c.can_move(move_dir):
            c.move(move_dir)
        return pos

    def _handle_pending_bridge(self, c: Controller, pos: Position, move_dir: Direction):
        """Build backwards diagonal bridge to follow an earlier call to self._handle_diagonal_step()"""
        if c.get_entity_type(
            c.get_tile_building_id(pos)
        ) == EntityType.ROAD and c.can_destroy(pos):
            c.destroy(pos)

        if c.can_build_bridge(pos, self.bridge_target):
            c.build_bridge(pos, self.bridge_target)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _navigate(self, c: Controller, target: Position) -> Direction:
        """Returns next move direction with bugnav pathfinding"""
        pos = self.current_pos

        if pos == target:
            self._bug_follow_state = None
            return None

        move_dir, self._bug_follow_state = bug_nav(
            c, pos, target, self._bug_follow_state
        )

        return move_dir

    def _try_build_harvester(self, c: Controller, pos: Position) -> bool:
        """Check cardinal directions and place a harvester (titanium first)"""
        built_harvester = False
        for d in DIRECTIONS_4:
            ore_pos = pos.add(d)

            if is_ore_titanium(c, ore_pos):
                self._clear_if_road(c, ore_pos)
                if c.can_build_harvester(ore_pos):
                    c.build_harvester(ore_pos)
                    self.titanium_found = True
                    built_harvester = True
                    break

            if (
                is_ore_axionite(c, ore_pos)
                and self.titanium_found
                and not self.axionite_found
                and not self.foundry_prev_placed
            ):
                self._clear_if_road(c, ore_pos)
                if c.can_build_harvester(ore_pos):
                    c.build_harvester(ore_pos)
                    self.axionite_found = True
                    built_harvester = True
                    break

        return built_harvester

    # --- Harvest States ---

    def _building_outward(self, c: Controller):
        """Build conveyors outward from core, place harvesters on adjacent ore"""
        pos = self.current_pos
        built_harvester = self._try_build_harvester(c, pos)

        if built_harvester:
            self.state = HarvestState.SEARCHING_ORES
            return

        self.target_pos = nearby_titanium(c, pos)
        if self.target_pos is not None:
            move_dir = self._navigate(c, self.target_pos)
            if move_dir is not None:
                self._build_and_move(c, pos, move_dir)
        else:
            outward_dir = self.core_pos.direction_to(pos)
            fallback_target = pos.add(
                outward_dir if outward_dir != Direction.CENTRE else random_direction_4()
            )

            if outward_dir in DIRECTIONS_4 and on_map(c, fallback_target):
                self.target_pos = fallback_target
            else:
                self.target_pos = None

            move_dir = self._navigate(c, fallback_target)
            if move_dir is not None:
                self._build_and_move(c, pos, move_dir)

    def _searching_ores(self, c: Controller):
        """After first ore, roam to find more ores while extending conveyor network"""
        pos = self.current_pos
        built_harvester = self._try_build_harvester(c, pos)

        if self.titanium_found and self.axionite_found and not self.foundry_prev_placed:
            self.state = HarvestState.PLACING_FOUNDRY
            return

        if built_harvester:
            return

        self.target_pos = nearby_ore(c, pos)
        if self.target_pos is not None:
            move_dir = self._navigate(c, self.target_pos)
            if move_dir is not None:
                self._build_and_move(c, pos, move_dir)
        else:
            self.target_pos = pos.add(random_direction_4())
            move_dir = self._navigate(c, self.target_pos)
            if move_dir is not None:
                self._build_and_move(c, pos, move_dir)

    def _placing_foundry(self, c: Controller):
        """Harvesters placed on ti and ax, trace conveyors to core and place foundry on its border"""
        pos = self.current_pos

        # Foundry placed: Wait for axionite then destroy foundry
        if self.foundry_curr_placed:
            if self.ax <= 0:
                return
            cost = c.get_conveyor_cost()[0]
            for tile in c.get_nearby_tiles(action_radius["bot"]):
                if is_tile_splitter(c, tile) and self.ti >= cost:
                    replace_with_conveyor(c, tile, self.core_pos)
                    self.splitter_for_foundry = False
                    if self.foundry_prev_placed:
                        self.state = HarvestState.BUILDING_OUTWARD
                    return
                elif is_tile_foundry(c, tile) and self.ti >= cost:
                    replace_with_conveyor(c, tile, self.core_pos)
                    self.foundry_prev_placed = True
                    if not self.splitter_for_foundry:
                        self.state = HarvestState.BUILDING_OUTWARD
                    return

        # Foundry not placed: Trace conveyor path back to core
        if is_tile_conveyor(c, pos):
            move_dir = c.get_direction(c.get_tile_building_id(pos))
            move_pos = pos.add(move_dir)
            cost_s, cost_f = c.get_splitter_cost()[0], c.get_foundry_cost()[0]

            left_pos = move_pos.add(move_dir.rotate_left().rotate_left())
            right_pos = move_pos.add(move_dir.rotate_right().rotate_right())
            foundry_pos = (
                left_pos if on_core_border(left_pos, self.core_pos) else right_pos
            )

            if (
                on_core_border(move_pos, self.core_pos)
                and not self.splitter_for_foundry
                and not is_tile_splitter(c, move_pos)
                and c.can_destroy(move_pos)
                and self.ti >= cost_s
            ):
                c.destroy(move_pos)
                if c.can_build_splitter(move_pos, move_dir):
                    c.build_splitter(move_pos, move_dir)
                    self.splitter_for_foundry = True
                    return
            elif (
                on_core_border(foundry_pos, self.core_pos)
                and self.splitter_for_foundry
                and not is_tile_foundry(c, foundry_pos)
                and c.can_destroy(foundry_pos)
                and self.ti >= cost_f
            ):
                c.destroy(foundry_pos)
                if c.can_build_foundry(foundry_pos):
                    c.build_foundry(foundry_pos)
                    self.foundry_curr_placed = True
                    return
            elif not on_core_border(move_pos, self.core_pos) and c.can_move(move_dir):
                c.move(move_dir)

    def _draw_debug(self, c: Controller):
        """Draw state-based dot and target line for debugging"""
        # State colors: BUILDING_OUTWARD=blue, SEARCHING_ORES=cyan, PLACING_FOUNDRY=yellow
        state_colors = {
            HarvestState.BUILDING_OUTWARD: (0, 0, 255),
            HarvestState.SEARCHING_ORES: (0, 255, 255),
            HarvestState.PLACING_FOUNDRY: (255, 255, 0),
        }
        r, g, b = state_colors.get(self.state, (255, 255, 255))
        c.draw_indicator_dot(self.current_pos, r, g, b)

        # Draw line to current navigation target (ore position)
        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, r, g, b)

    def run(self, c: Controller):
        self.current_pos = c.get_position()
        self.ti, self.ax = c.get_global_resources()
        self._check_for_foundry(c)

        match self.state:
            case HarvestState.BUILDING_OUTWARD:
                self._building_outward(c)
            case HarvestState.SEARCHING_ORES:
                self._searching_ores(c)
            case HarvestState.PLACING_FOUNDRY:
                self._placing_foundry(c)

        self._draw_debug(c)
