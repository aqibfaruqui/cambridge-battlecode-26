from cambc import Controller
from utils.movement import (
    random_direction_8,
)

class Core:
    def __init__(self):
        self.builders_spawned = 0
        self.builders_max = 8

    def run(self, c: Controller):
        if self.builders_spawned < self.builders_max:
            spawn_pos = c.get_position().add(random_direction_8())
            if c.can_spawn(spawn_pos):
                c.spawn_builder(spawn_pos)
                self.builders_spawned += 1