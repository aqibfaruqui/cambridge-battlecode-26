from enum import Enum
from cambc import Controller, Direction, EntityType, Position, Environment
from utils.movement import (
    random_direction_4,
    bug_nav,
)


class HarvestState(Enum):
    __slots__ = ()

    BUILDING_OUTWARD = "building_outward"
    SEARCHING_ORES = "searching_ores"


class Harvester:
    def __init__(self, core_pos: Position):
        self.state = HarvestState.BUILDING_OUTWARD
        self.core_pos = core_pos
        self.current_pos = None
        self._bug_follow_state: dict | None = None

    def _is_ore_tile(self, c: Controller, pos: Position) -> bool:
        if not (0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()):
            return False
        env = c.get_tile_env(pos)
        return env in (Environment.ORE_TITANIUM, Environment.ORE_AXIONITE)

    def _try_build_adjacent_harvesters(self, c: Controller, pos: Position) -> bool:
        built_harvester = False
        for d in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
            ore_pos = pos.add(d)
            if self._is_ore_tile(c, ore_pos) and c.can_build_harvester(ore_pos):
                c.build_harvester(ore_pos)
                built_harvester = True
        return built_harvester

    def _nearest_ore_tile(self, c: Controller, pos: Position):
        for tile in c.get_nearby_tiles():
            if self._is_ore_tile(c, tile):
                build_id = c.get_tile_building_id(tile)
                if not build_id:
                    return tile
        return None

    def _build_and_move(self, c: Controller, pos: Position, move_dir: Direction):
        if move_dir == Direction.CENTRE:
            move_dir = random_direction_4()

        if move_dir in (
            Direction.NORTHEAST,
            Direction.NORTHWEST,
            Direction.SOUTHEAST,
            Direction.SOUTHWEST,
        ):
            move_dir = move_dir.rotate_left()

        next_pos = pos.add(move_dir)
        conveyor_dir = move_dir.opposite()
        next_is_ore = self._is_ore_tile(c, next_pos)

        next_bid = c.get_tile_building_id(next_pos)
        if (
            not next_is_ore
            and next_bid is not None
            and c.get_entity_type(next_bid) == EntityType.ROAD
            and c.can_destroy(next_pos)
        ):
            c.destroy(next_pos)

        if (not next_is_ore) and c.can_build_conveyor(next_pos, conveyor_dir):
            c.build_conveyor(next_pos, conveyor_dir)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _building_outward(self, c: Controller):
        """Build conveyors outward from core, place harvesters on adjacent ore"""
        pos = self.current_pos
        built_harvester = self._try_build_adjacent_harvesters(c, pos)

        if built_harvester:
            self.state = HarvestState.SEARCHING_ORES

        target_pos = self._nearest_ore_tile(c, pos)
        if target_pos is not None:
            self._navigate(c, target_pos)
        else:
            outward_dir = self.core_pos.direction_to(pos)
            target = pos.add(
                outward_dir if outward_dir != Direction.CENTRE else random_direction_4()
            )
            self._navigate(c, target)

    def _searching_ores(self, c: Controller):
        """After first ore, roam to find more ores while extending conveyor network"""
        pos = self.current_pos

        self._try_build_adjacent_harvesters(c, pos)

        target_pos = self._nearest_ore_tile(c, pos)
        if target_pos is not None:
            self._navigate(c, target_pos)
        else:
            self._navigate(c, pos.add(random_direction_4()))

    def _navigate(self, c: Controller, target: Position) -> None:
        pos = self.current_pos

        if pos == target:
            self._bug_follow_state = None
            return

        move_dir, self._bug_follow_state = bug_nav(
            c, pos, target, self._bug_follow_state
        )
        if move_dir is not None:
            self._build_and_move(c, pos, move_dir)

    def run(self, c: Controller):
        self.current_pos = c.get_position()

        match self.state:
            case HarvestState.BUILDING_OUTWARD:
                self._building_outward(c)
            case HarvestState.SEARCHING_ORES:
                self._searching_ores(c)
