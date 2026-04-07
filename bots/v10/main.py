"""
V4 Bot:
- Core: Spawn 8 bots on random adjacent tiles
- Builder Bot: Designate half to build conveyors from spawn and find ores
               Designate half to exploring and building turrets at enemy core

Test code runs with: cambc run v2 v4
"""

from cambc import Controller, EntityType
from core.core import Core
from builders.builder import Builder
from turrets.turret import Turret


class Player:
    def __init__(self):
        self.unit = None

    def _init_unit(self, c: Controller):
        unit_etype = c.get_entity_type()
        match unit_etype:
            case EntityType.CORE:
                return Core()
            case EntityType.BUILDER_BOT:
                return Builder()
            case _:
                return Turret(unit_etype)

    def run(self, c: Controller):
        if self.unit is None:
            self.unit = self._init_unit(c)

        self.unit.run(c)
