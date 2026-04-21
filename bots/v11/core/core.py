from cambc import Controller, EntityType, Position
from builders.builder import BuilderType


_ENEMY_THREAT_TYPES = frozenset(
    {
        EntityType.BUILDER_BOT,
        EntityType.CONVEYOR,
        EntityType.GUNNER,
        EntityType.SENTINEL,
        EntityType.BREACH,
        EntityType.LAUNCHER,
    }
)


class Core:
    def __init__(self):
        self.builders_spawned = 0
        self.default_spawn_plan = [
            BuilderType.HARVESTER_1,
            BuilderType.ATTACKER_REVAMPED,
            BuilderType.HARVESTER_2,
            BuilderType.ATTACKER_REVAMPED,
            # BuilderType.HARVESTER_1,
        ]
        self.spawn_plan = self.default_spawn_plan.copy()
        self.healer_id: int | None = None
        self.last_periodic_attacker_round = 0

    def _has_enemy_threat_in_vision(self, c: Controller) -> bool:
        my_team = c.get_team()
        for eid in c.get_nearby_entities():
            if c.get_team(eid) == my_team:
                continue
            if c.get_entity_type(eid) in _ENEMY_THREAT_TYPES:
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
        if c.get_current_round() in {1000, 1001}:
            self.spawn_plan = self.default_spawn_plan.copy()

        if self.builders_spawned < len(self.spawn_plan):
            builder_type = self.spawn_plan[self.builders_spawned]
            if self._try_spawn(c, builder_type) is not None:
                self.builders_spawned += 1
            return

        round_now = c.get_current_round()
        if (
            round_now > 200
            and round_now - self.last_periodic_attacker_round >= 50
            and c.get_scale_percent() < 600
        ):
            print("Periodic attacker spawn check")
            if self._try_spawn(c, BuilderType.ATTACKER_REVAMPED) is not None:
                print("Spawned periodic attacker")
                self.last_periodic_attacker_round = round_now
                return

        if self._healer_alive(c):
            return
        if round_now < 10:
            return
        if not self._has_enemy_threat_in_vision(c):
            return
        new_id = self._try_spawn(c, BuilderType.HEALER)
        if new_id is not None:
            self.healer_id = new_id
