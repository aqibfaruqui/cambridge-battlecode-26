from typing import Optional

from cambc import Controller
from action.interface import Behaviour
from entity.builder.roles import BuilderType
from entity.builder.behaviour import explorer
from world.tracking import find_core_pos


class Builder:
    def __init__(self, c: Controller):
        self.builder_type: Optional[BuilderType] = None
        self.behaviour: Optional[Behaviour] = None
        self._core_pos = None
        self.c = c

    def run(self, c: Controller):
        self._core_pos = find_core_pos(c, self._core_pos)
        if self.behaviour is None:
            self.behaviour = self._create_behaviour(c)

        self.behaviour.tick(c)

    def _create_behaviour(self, c: Controller) -> Behaviour:
        if self._core_pos is None:
            raise RuntimeError("Core position not found")
        dx = c.get_position().x - self._core_pos.x
        dy = c.get_position().y - self._core_pos.y
        builder_type = BuilderType.from_offset(dx, dy)
        self.builder_type = builder_type
        match builder_type:
            case BuilderType.RANDOM_EXPLORER:
                return explorer.Explorer(c)
            case _:
                raise RuntimeError(f"Builder type {builder_type.name} not implemented")
