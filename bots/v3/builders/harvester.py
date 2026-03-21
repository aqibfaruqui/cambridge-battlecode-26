from enum import Enum
from cambc import Controller, Direction, EntityType, Environment, Position
from utils.movement import (
    get_direction_4,
    random_direction_8,
    reached_core,
    is_diagonal,
    split_diagonal,
    on_map,
)


class HarvestState(Enum):
    __slots__ = ()

    NOT_PLACED = "not_placed"
    JUST_PLACED = "just_placed"
    RETURNING_TO_CORE = "returning_to_core"


class Harvester:
    def __init__(self, core_pos: Position):
        self.state = HarvestState.NOT_PLACED
        self.core_pos = core_pos
        self.current_pos = None
        self.harvester_pos = None

    def _not_placed(self, c: Controller):
        """Randomly explore and build harvesters (in first 100 turns)"""
        if self.state == HarvestState.NOT_PLACED:
            ti, _ = c.get_harvester_cost()
            if ti < 1000 and c.get_current_round() < 1500:
                for d in Direction:
                    ore_pos = self.current_pos.add(d)
                    if not on_map(c, ore_pos):
                        continue

                    next_to_ore = (
                        c.get_tile_env(ore_pos) == Environment.ORE_AXIONITE
                        or c.get_tile_env(ore_pos) == Environment.ORE_TITANIUM
                    )
                    next_to_road = (
                        c.get_entity_type(c.get_tile_building_id(ore_pos))
                        == EntityType.ROAD
                    )

                    if next_to_ore and next_to_road and c.can_destroy(ore_pos):
                        c.destroy(ore_pos)

                    if c.can_build_harvester(ore_pos):
                        c.build_harvester(ore_pos)
                        self.state = HarvestState.JUST_PLACED
                        self.harvester_pos = ore_pos
                        return

            move_dir = random_direction_8()
            move_pos = self.current_pos.add(move_dir)

            if c.can_build_road(move_pos):
                c.build_road(move_pos)

            if c.can_move(move_dir):
                c.move(move_dir)

    def _just_placed(self, c: Controller):
        """If builder has just placed harvester, build first connecting conveyor"""
        move_pos = self.current_pos

        if self.harvester_pos and is_diagonal(self.current_pos, self.harvester_pos):
            ns, ew = split_diagonal(self.current_pos, self.harvester_pos)
            m1 = self.current_pos.add(ns)
            m2 = self.current_pos.add(ew)
            move_pos = (
                m1
                if m1.distance_squared(self.core_pos)
                < m2.distance_squared(self.core_pos)
                else m2
            )

        conveyor_dir = get_direction_4(move_pos, self.core_pos)

        if c.get_entity_type(
            c.get_tile_building_id(move_pos)
        ) == EntityType.ROAD and c.can_destroy(move_pos):
            c.destroy(move_pos)

        if c.can_build_conveyor(move_pos, conveyor_dir):
            c.build_conveyor(move_pos, conveyor_dir)

        if self.current_pos != move_pos:
            step_to_first_conveyor = get_direction_4(self.current_pos, move_pos)
            if c.can_move(step_to_first_conveyor):
                c.move(step_to_first_conveyor)
            else:
                return

        self.state = HarvestState.RETURNING_TO_CORE

    def _returning_to_core(self, c: Controller):
        """If builder has placed harvester, lay conveyor path back to core"""
        if self.state == HarvestState.RETURNING_TO_CORE:
            if self.current_pos == self.core_pos:
                self.state = HarvestState.NOT_PLACED
                return

            move_dir = get_direction_4(self.current_pos, self.core_pos)

            move_pos = self.current_pos.add(move_dir)

            entity_type = c.get_entity_type(c.get_tile_building_id(move_pos))
            if entity_type == EntityType.ROAD and c.can_destroy(move_pos):
                c.destroy(move_pos)

            next_move_dir = get_direction_4(
                move_pos, self.core_pos
            )  # For conveyors to turn corners

            if c.can_build_conveyor(move_pos, next_move_dir):
                c.build_conveyor(move_pos, next_move_dir)

            if c.can_move(move_dir):
                c.move(move_dir)

            if reached_core(c.get_position(), self.core_pos):
                self.state = HarvestState.NOT_PLACED

    def run(self, c: Controller):
        self.current_pos = c.get_position()

        match self.state:
            case HarvestState.NOT_PLACED:
                self._not_placed(c)
            case HarvestState.JUST_PLACED:
                self._just_placed(c)
            case HarvestState.RETURNING_TO_CORE:
                self._returning_to_core(c)
