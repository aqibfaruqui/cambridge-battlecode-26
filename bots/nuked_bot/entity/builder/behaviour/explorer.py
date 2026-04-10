import random

from action.interface import Behaviour
from action.navigation import Goto
from cambc import Controller, Position
from world.raw_map_representation import EnvironmentMap


class Explorer(Behaviour):
    def __init__(self, c: Controller):
        super().__init__()
        self._map = EnvironmentMap(c.get_map_width(), c.get_map_height())

    def idle(self, c: Controller) -> None:
        print("I am an explorer")
        if not self.actions:
            x = random.randint(0, c.get_map_width() - 1)
            y = random.randint(0, c.get_map_height() - 1)
            self.actions.append(Goto([Position(x, y)], env_map=self._map))

    def tick(self, c: Controller) -> None:
        super().tick(c)
