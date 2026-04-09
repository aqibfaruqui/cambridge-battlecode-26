from cambc import EntityType, Controller, Position
from world.state import GlobalState


class Launcher:
    def __init__(self):
        self.global_state = GlobalState(track_core=True, track_enemy_core=True)

    def _find_throw_target(self, c: Controller) -> Position | None:
        self.global_state.update(c)
        print(self.global_state)
        core_pos = self.global_state.try_core_pos()
        enemy_core_pos = self.global_state.try_enemy_core_pos()

        away_from = c.get_position()
        nearer_to = None
        if enemy_core_pos is not None:
            nearer_to = enemy_core_pos
        elif core_pos is not None:
            away_from = core_pos

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
            print(f"Couldn't find a target for enemy at {nearby_enemies[0]}")
            return

        if c.can_launch(nearby_enemies[0], target):
            c.launch(nearby_enemies[0], target)
            print(f"Launched bot at {nearby_enemies[0]} at {target}")
