import random

from action.interface import Behaviour
from action.navigation import Goto
from cambc import Controller, Position


class Explorer(Behaviour):
    def __init__(self):
        super().__init__()

    def idle(self, c: Controller) -> None:
        print("I am an explorer")
        if not self.actions:
            x = random.randint(0, c.get_map_width() - 1)
            y = random.randint(0, c.get_map_height() - 1)
            self.actions.append(Goto([Position(x, y)]))

    def tick(self, c: Controller) -> None:
        super().tick(c)
