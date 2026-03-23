from enum import Enum
from cambc import Controller, Direction, EntityType, Position, Environment
from utils.movement import (
    random_direction_4,
    on_map,
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

        self.bridge_target = None

    def _clear_if_road(self, c: Controller, pos: Position):
        build_id = c.get_tile_building_id(pos)
        if build_id is not None and c.get_entity_type(build_id) == EntityType.ROAD:
            if c.can_destroy(pos):
                c.destroy(pos)

    def _is_ore_tile(self, c: Controller, pos: Position) -> bool:
        if not on_map(c, pos):
            return False
        env = c.get_tile_env(pos)
        return env == Environment.ORE_TITANIUM

    def _try_build_adjacent_harvesters(self, c: Controller, pos: Position) -> bool:
        built_harvester = False
        for d in (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST):
            ore_pos = pos.add(d)
            if self._is_ore_tile(c, ore_pos):
                self._clear_if_road(c, ore_pos)
                if c.can_build_harvester(ore_pos):
                    c.build_harvester(ore_pos)
                    built_harvester = True

        return built_harvester

    def _nearest_ore_tile(self, c: Controller, pos: Position):
        for tile in c.get_nearby_tiles():
            if not self._is_ore_tile(c, tile):
                continue

            build_id = c.get_tile_building_id(tile)
            if build_id is None:
                return tile

            etype = c.get_entity_type(build_id)
            if etype == EntityType.ROAD and c.can_destroy(tile):
                return tile

            continue

        return None

    def _build_and_move(self, c: Controller, pos: Position, move_dir: Direction):
        if move_dir == Direction.CENTRE:
            move_dir = random_direction_4()

        bridge_target = None

        if move_dir in (
            Direction.NORTHEAST,
            Direction.NORTHWEST,
            Direction.SOUTHEAST,
            Direction.SOUTHWEST,
        ):
            left_pos = pos.add(move_dir.rotate_left())
            right_pos = pos.add(move_dir.rotate_right())
            if (
                c.get_tile_env(left_pos) == Environment.WALL
                and c.get_tile_env(right_pos) == Environment.WALL
            ):
                bridge_target = pos
            else:
                move_dir = move_dir.rotate_left()

        next_pos = pos.add(move_dir)

        if move_dir in (
            Direction.NORTHEAST,
            Direction.NORTHWEST,
            Direction.SOUTHEAST,
            Direction.SOUTHWEST,
        ):
            # move diagonally, not placing anything (bridge placed on next turn)

            # build road in new place
            move_pos = pos.add(move_dir)

            if c.get_tile_env(move_pos) == Environment.EMPTY:
                # build road
                if c.can_build_road(move_pos):
                    c.build_road(move_pos)

            # move to new place
            if c.can_move(move_dir):
                c.move(move_dir)

            bridge_target = pos
        else:
            if self.bridge_target:
                # try to place bridge if we built one on the previous diagonal move

                # destroy road at current position
                if c.get_entity_type(
                    c.get_tile_building_id(pos)
                ) == EntityType.ROAD and c.can_destroy(pos):
                    c.destroy(pos)

                # build bridge to bridge target
                if c.can_build_bridge(pos, self.bridge_target):
                    c.build_bridge(pos, self.bridge_target)

                bridge_target = None

            else:
                # normal conveyer logic
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

            # Always move if possible (whether we built bridge or conveyor)
            if c.can_move(move_dir):
                c.move(move_dir)

        self.bridge_target = bridge_target

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

    def run(self, c: Controller):
        self.current_pos = c.get_position()

        match self.state:
            case HarvestState.BUILDING_OUTWARD:
                self._building_outward(c)
            case HarvestState.SEARCHING_ORES:
                self._searching_ores(c)
