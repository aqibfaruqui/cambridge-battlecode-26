from cambc import Controller
from utils.movement import (
    DIRECTIONS_4,
    direction_to_centre,
)


class Core:
    def __init__(self):
        self.builders_spawned = 0
        self.builders_max = 8

    def run(self, c: Controller):
        if self.builders_spawned < self.builders_max:
            core_pos = c.get_position()
            if self.builders_spawned < 6:
                spawn_dir = DIRECTIONS_4[self.builders_spawned % 4]  # HARVESTER
            else:
                spawn_dir = direction_to_centre(c, core_pos)  # ATTACKER
                if spawn_dir in DIRECTIONS_4:
                    spawn_dir = spawn_dir.rotate_right()

            spawn_pos = core_pos.add(spawn_dir)
            if c.can_spawn(spawn_pos):
                c.spawn_builder(spawn_pos)
                self.builders_spawned += 1
