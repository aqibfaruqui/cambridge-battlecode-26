from cambc import Position, Controller, EntityType


_THROW_RANGE_SQ = 26
_THROW_SPAN = 5


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

    def _legal_throw_tiles(self, c: Controller, bot_pos: Position) -> list[Position]:
        my_pos = c.get_position()
        tiles: list[Position] = []
        for dx in range(-_THROW_SPAN, _THROW_SPAN + 1):
            for dy in range(-_THROW_SPAN, _THROW_SPAN + 1):
                if dx == 0 and dy == 0:
                    continue
                if dx * dx + dy * dy > _THROW_RANGE_SQ:
                    continue
                cand = Position(my_pos.x + dx, my_pos.y + dy)
                if c.can_launch(bot_pos, cand):
                    tiles.append(cand)
        return tiles

    def _find_enemy_core(self, c: Controller) -> Position | None:
        my_team = c.get_team()
        for bid in c.get_nearby_buildings():
            if c.get_entity_type(bid) != EntityType.CORE:
                continue
            if c.get_team(bid) == my_team:
                continue
            return c.get_position(bid)
        return None

    def _friendly_builder_positions(self, c: Controller) -> list[Position]:
        my_team = c.get_team()
        return [
            c.get_position(eid)
            for eid in c.get_nearby_entities()
            if c.get_team(eid) == my_team
            and c.get_entity_type(eid) == EntityType.BUILDER_BOT
        ]

    def run(self, c: Controller):
        nearby_enemies = [
            c.get_position(e)
            for e in c.get_nearby_entities(2)
            if c.get_team(e) != c.get_team()
            and c.get_entity_type(e) == EntityType.BUILDER_BOT
        ]

        if not nearby_enemies:
            self.idle_rounds += 1
            if self.idle_rounds > 200:
                c.self_destruct()
            return

        enemy_pos = nearby_enemies[0]

        # Priority 1: enemy core in vision → throw as close to it as possible.
        enemy_core = self._find_enemy_core(c)
        if enemy_core is not None:
            tiles = self._legal_throw_tiles(c, enemy_pos)
            if tiles:
                dest = min(tiles, key=lambda p: p.distance_squared(enemy_core))
                c.launch(enemy_pos, dest)
                self.idle_rounds = 0
                print(
                    f"Launched bot at {enemy_pos} toward enemy core {enemy_core} via {dest}"
                )
                return

        # Priority 2: throw onto the road farthest from our core.
        target = self._find_throw_target(c)
        if target is not None and c.can_launch(enemy_pos, target):
            c.launch(enemy_pos, target)
            self.idle_rounds = 0
            print(f"Launched bot at {enemy_pos} at {target}")
            return

        # Priority 3: no road target — throw as far as possible from our builders.
        friendlies = self._friendly_builder_positions(c)
        tiles = self._legal_throw_tiles(c, enemy_pos)
        if tiles:
            if friendlies:
                dest = max(
                    tiles,
                    key=lambda p: min(p.distance_squared(f) for f in friendlies),
                )
            else:
                dest = tiles[0]
            c.launch(enemy_pos, dest)
            self.idle_rounds = 0
            print(f"Launched bot at {enemy_pos} away from builders via {dest}")
            return

        if target is None:
            print(f"Couldn't find a target for enemy at {enemy_pos}")
            self.idle_rounds += 1
            if self.idle_rounds > 400:
                c.self_destruct()
            return

        self.idle_rounds += 1
        if self.idle_rounds > 50:
            c.self_destruct()
