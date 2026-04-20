from cambc import Controller, EntityType, Position
from builders.builder import BuilderType


class Core:
    def __init__(self):
        self.builders_spawned = 0
        self.spawn_plan = [
            BuilderType.HARVESTER_1,
            BuilderType.HARVESTER_2,
            BuilderType.ATTACKER_REVAMPED,
            BuilderType.ATTACKER_REVAMPED,
        ]
        self.healer_id: int | None = None

    def _has_friendly_conveyor_in_vision(self, c: Controller) -> bool:
        my_team = c.get_team()
        for bid in c.get_nearby_buildings(16):
            if c.get_team(bid) != my_team:
                continue
            if c.get_entity_type(bid) == EntityType.CONVEYOR:
                return True
        return False

    def _builder_bot_on_core_ring(self, c: Controller) -> bool:
        core_pos = c.get_position()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                p = Position(core_pos.x + dx, core_pos.y + dy)
                if c.get_tile_builder_bot_id(p) is not None:
                    return True
        return False

    def _healer_alive(self, c: Controller) -> bool:
        if self.healer_id is None:
            return False
        return self.healer_id in c.get_nearby_units()

    def _try_spawn(self, c: Controller, builder_type: BuilderType) -> int | None:
        spawn_pos = builder_type.position_from_core(c.get_position())
        if not c.can_spawn(spawn_pos):
            return None
        return c.spawn_builder(spawn_pos)

    def run(self, c: Controller):
        # Hold the core's 3x3 clear so only one builder is spawning at a time.
        if self._builder_bot_on_core_ring(c):
            return

        if self.builders_spawned < len(self.spawn_plan):
            builder_type = self.spawn_plan[self.builders_spawned]
            if self._try_spawn(c, builder_type) is not None:
                self.builders_spawned += 1
            return

        if self._healer_alive(c):
            return
        if c.get_current_round() < 10:
            return
        if not self._has_friendly_conveyor_in_vision(c):
            return
        new_id = self._try_spawn(c, BuilderType.HEALER)
        if new_id is not None:
            self.healer_id = new_id
