from enum import Enum
from cambc import Controller, Direction, EntityType, Position
from utils.movement import (
    DIRECTIONS_4,
    random_direction_4,
    bug_nav,
)
from utils.board import (
    is_ore_titanium,
    is_ore_axionite,
    is_ore,
    nearest_ore_tile,
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
        self.first_conveyor_pos = None
        self.titanium_found = False
        self.axionite_found = False
        self.foundry_placed = False
        self.cost_scale = 100.0
        self._bug_follow_state: dict | None = None

    def _clear_if_road(self, c: Controller, pos: Position):
        build_id = c.get_tile_building_id(pos)
        if (
            build_id is not None
            and c.get_entity_type(build_id) == EntityType.ROAD
            and c.can_destroy(pos)
        ):
            c.destroy(pos)

    def _try_build_harvester(self, c: Controller, pos: Position) -> bool:
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
                and not self.foundry_placed
            ):
                self._clear_if_road(c, ore_pos)
                if c.can_build_harvester(ore_pos):
                    c.build_harvester(ore_pos)
                    self.axionite_found = True
                    built_harvester = True
                    break

        return built_harvester

    def _move(self, c: Controller, pos: Position, move_dir):
        move_pos = pos.add(move_dir)

        if c.can_build_road(move_pos):
            c.build_road(move_pos)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _build_conveyor_and_move(
        self, c: Controller, pos: Position, move_dir: Direction
    ):
        """Place backwards conveyor in movement direction and move to it"""
        if move_dir == Direction.CENTRE:
            move_dir = random_direction_4()

        if move_dir != Direction.CENTRE and move_dir not in DIRECTIONS_4:
            move_dir = move_dir.rotate_left()

        move_pos = pos.add(move_dir)
        conveyor_dir = move_dir.opposite()

        if not is_ore(c, move_pos):
            self._clear_if_road(c, move_pos)

        if not is_ore(c, move_pos) and c.can_build_conveyor(move_pos, conveyor_dir):
            c.build_conveyor(move_pos, conveyor_dir)
            if self.first_conveyor_pos is None:
                self.first_conveyor_pos = move_pos

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

    def _trace_conveyors(self, c: Controller):
        """"""
        pass

    def _building_outward(self, c: Controller):
        """Build conveyors outward from core, place harvesters on adjacent ore"""
        pos = self.current_pos
        built_harvester = self._try_build_harvester(c, pos)

        if built_harvester:
            self.state = HarvestState.SEARCHING_ORES

        target_pos = nearest_ore_tile(c, pos)
        if target_pos is not None:
            move_dir = self._navigate(c, target_pos)
            if move_dir is not None:
                self._build_conveyor_and_move(c, pos, move_dir)
        else:
            outward_dir = self.core_pos.direction_to(pos)
            target = pos.add(
                outward_dir if outward_dir != Direction.CENTRE else random_direction_4()
            )
            move_dir = self._navigate(c, target)
            if move_dir is not None:
                self._build_conveyor_and_move(c, pos, move_dir)

    def _searching_ores(self, c: Controller):
        """After first ore, roam to find more ores while extending conveyor network"""
        pos = self.current_pos
        self._try_build_harvester(c, pos)

        if self.titanium_found and self.axionite_found and not self.foundry_placed:
            self.state = HarvestState.PLACING_FOUNDRY
            return

        target_pos = nearest_ore_tile(c, pos)
        if target_pos is not None:
            move_dir = self._navigate(c, target_pos)
            if move_dir is not None:
                self._build_conveyor_and_move(c, pos, move_dir)
        else:
            move_dir = self._navigate(c, pos.add(random_direction_4()))
            if move_dir is not None:
                self._build_conveyor_and_move(c, pos, move_dir)

    def _placing_foundry(self, c: Controller):
        """Harvesters placed on ti and ax, trace conveyors to core and place foundry on its border"""
        pos = self.current_pos

        build_id = c.get_tile_building_id(pos)
        if build_id is not None and c.get_entity_type(build_id) == EntityType.CONVEYOR:
            move_dir = c.get_direction(build_id)
            move_pos = pos.add(move_dir)
            ti_r, _ = c.get_global_resources()
            ti_c, _ = c.get_foundry_cost()
            if (
                on_core_border(move_pos, self.core_pos)
                and c.can_destroy(move_pos)
                and ti_r >= ti_c
            ):
                c.destroy(move_pos)
                if c.can_build_foundry(move_pos):
                    c.build_foundry(move_pos)
                    self.foundry_placed = True
                    self.state = HarvestState.SEARCHING_ORES
                    return
            elif c.can_move(move_dir):
                c.move(move_dir)

    def run(self, c: Controller):
        self.current_pos = c.get_position()
        if c.get_scale_percent() >= self.cost_scale + 100.0:
            self.foundry_placed = True
        self.cost_scale = c.get_scale_percent()

        print(f"In state: {self.state}")
        print(f"Seen titanium (true/false): {self.titanium_found}")
        print(f"Seen axionite (true/false): {self.axionite_found}")
        print(f"Foundry cost: {c.get_foundry_cost()}")

        match self.state:
            case HarvestState.BUILDING_OUTWARD:
                self._building_outward(c)
            case HarvestState.SEARCHING_ORES:
                self._searching_ores(c)
            case HarvestState.PLACING_FOUNDRY:
                self._placing_foundry(c)
