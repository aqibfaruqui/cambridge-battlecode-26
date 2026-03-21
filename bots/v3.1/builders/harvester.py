from enum import Enum
from cambc import Controller, Direction, EntityType, Position, Environment
from utils.movement import (
    random_direction_4,
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

    def _nearest_ore_tile(self, c: Controller, pos: Position):
        for tile in c.get_nearby_tiles():
            env = c.get_tile_env(tile)
            if env == Environment.ORE_TITANIUM or env == Environment.ORE_AXIONITE:
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

        next_bid = c.get_tile_building_id(next_pos)
        if (
            next_bid is not None
            and c.get_entity_type(next_bid) == EntityType.ROAD
            and c.can_destroy(next_pos)
        ):
            c.destroy(next_pos)

        if c.can_build_conveyor(next_pos, conveyor_dir):
            c.build_conveyor(next_pos, conveyor_dir)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _building_outward(self, c: Controller):
        """Build conveyors outward from core, place harvesters on adjacent ore"""
        pos = self.current_pos
        built_harvester = False

        # Place harvesters on all adjacent ore tiles
        for d in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
            ore_pos = pos.add(d)
            if c.can_build_harvester(ore_pos):
                c.build_harvester(ore_pos)
                built_harvester = True

        if built_harvester:
            self.state = HarvestState.SEARCHING_ORES

        target_pos = self._nearest_ore_tile(c, pos)
        if target_pos is not None:
            move_dir = pos.direction_to(target_pos)
        else:
            outward_dir = self.core_pos.direction_to(pos)
            move_dir = (
                outward_dir if outward_dir != Direction.CENTRE else random_direction_4()
            )

        self._build_and_move(c, pos, move_dir)

    def _searching_ores(self, c: Controller):
        """After first ore, roam to find more ores while extending conveyor network"""
        pos = self.current_pos

        for d in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
            ore_pos = pos.add(d)
            if c.can_build_harvester(ore_pos):
                c.build_harvester(ore_pos)

        target_pos = self._nearest_ore_tile(c, pos)
        if target_pos is not None:
            move_dir = pos.direction_to(target_pos)
        else:
            move_dir = random_direction_4()

        self._build_and_move(c, pos, move_dir)

    def run(self, c: Controller):
        self.current_pos = c.get_position()

        match self.state:
            case HarvestState.BUILDING_OUTWARD:
                self._building_outward(c)
            case HarvestState.SEARCHING_ORES:
                self._searching_ores(c)
