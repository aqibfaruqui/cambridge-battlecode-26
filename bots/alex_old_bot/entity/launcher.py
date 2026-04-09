from cambc import EntityType, Controller, Position
from world.tracking import find_core_pos, find_enemy_core_pos


class Launcher:
    def __init__(self):
        self._core_pos = None
        self._enemy_core_pos = None

    def _find_throw_target(self, c: Controller) -> Position | None:
        self._core_pos = find_core_pos(c, self._core_pos)
        self._enemy_core_pos = find_enemy_core_pos(c, self._enemy_core_pos)

        away_from = c.get_position()
        nearer_to = None
        if self._enemy_core_pos is not None:
            nearer_to = self._enemy_core_pos
        elif self._core_pos is not None:
            away_from = self._core_pos

        roads = [
            c.get_position(bid)
            for bid in c.get_nearby_buildings()
            if c.get_entity_type(bid) == EntityType.ROAD
        ]

        if not roads:
            return None

        roads.sort(
            key=lambda pos: pos.distance_squared(
                nearer_to if nearer_to is not None else away_from
            )
        )

        if nearer_to is None:
            roads.reverse()

        return roads[0]

    def run(self, c: Controller):
        target = self._find_throw_target(c)
        nearby_enemies = [
            c.get_position(e)
            for e in c.get_nearby_entities(2)
            if c.get_team(e) != c.get_team()
            and c.get_entity_type(e) == EntityType.BUILDER_BOT
        ]

        if not nearby_enemies:
            return

        if target is None:
            return

        if c.can_launch(nearby_enemies[0], target):
            c.launch(nearby_enemies[0], target)
