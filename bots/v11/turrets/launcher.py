from cambc import Position, Controller, EntityType

class Launcher:
    def __init__(self, core_pos: Position | None):
        self.core_pos = core_pos
        self.idle_rounds = 0

    def _find_throw_target(self, c: Controller) -> Position | None:
        roads = [
            c.get_position(bid)
            for bid in c.get_nearby_buildings()
            if c.get_entity_type(bid) == EntityType.ROAD
        ]

        if not roads:
            return None

        roads.sort(
            key=lambda pos: pos.distance_squared(
                self.core_pos if self.core_pos is not None else Position(0, 0)
            )
        )

        return roads[-1]

    def run(self, c: Controller):
        target = self._find_throw_target(c)
        nearby_enemies = [
            c.get_position(e)
            for e in c.get_nearby_entities(2)
            if c.get_team(e) != c.get_team()
            and c.get_entity_type(e) == EntityType.BUILDER_BOT
        ]

        if not nearby_enemies:
            self.idle_rounds += 1
            if self.idle_rounds > 50:
                c.self_destruct()
            return

        if target is None:
            print(f"Couldn't find a target for enemy at {nearby_enemies[0]}")
            self.idle_rounds += 1
            if self.idle_rounds > 200:
                c.self_destruct()
            return

        if c.can_launch(nearby_enemies[0], target):
            c.launch(nearby_enemies[0], target)
            self.idle_rounds = 0
            print(f"Launched bot at {nearby_enemies[0]} at {target}")
        else:
            self.idle_rounds += 1
            if self.idle_rounds > 50:
                c.self_destruct()