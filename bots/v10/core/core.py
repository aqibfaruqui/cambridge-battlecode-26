from cambc import Controller
from builders.builder import BuilderType


class Core:
    def __init__(self):
        self.builders_spawned = 0
        self.spawn_plan = [
            BuilderType.HARVESTER,
            BuilderType.HARVESTER,
            BuilderType.HARVESTER,
            BuilderType.ATTACKER,
            BuilderType.ATTACKER,
            BuilderType.HEALER,
        ]

    def run(self, c: Controller):
        if self.builders_spawned >= len(self.spawn_plan):
            return

        core_pos = c.get_position()
        builder_type = self.spawn_plan[self.builders_spawned]
        if builder_type == BuilderType.HEALER and c.get_current_round() < 40:
            return

        spawn_pos = builder_type.position_from_core(core_pos)
        if c.can_spawn(spawn_pos):
            c.spawn_builder(spawn_pos)
            self.builders_spawned += 1
