from typing import Optional

from cambc import Controller
from action.interface import Behaviour
from entity.builder.roles import BuilderType
from entity.builder.behaviour import explorer, force_killer
from world.state import GlobalState


class Builder:
    def __init__(self):
        self.builder_type: Optional[BuilderType] = None
        self.behaviour: Optional[Behaviour] = None
        self.global_state = GlobalState(track_core=True, track_enemy_core=True)

    def run(self, c: Controller):
        self.global_state.update(c)
        if self.behaviour is None:
            self.behaviour = self._create_behaviour(c)

        print(f"Builder {self.builder_type.name} running a behaviour tick.")
        self.behaviour.tick(c)

    def _create_behaviour(self, c: Controller) -> Behaviour:
        core_pos = self.global_state.get_core_pos()
        dx, dy = c.get_position().x - core_pos.x, c.get_position().y - core_pos.y
        builder_type = BuilderType.from_offset(dx, dy)
        self.builder_type = builder_type
        match builder_type:
            case BuilderType.RANDOM_EXPLORER:
                return explorer.Explorer(explorer.Navigator.RANDOM)
            case BuilderType.FORCE_KILLER:
                return force_killer.ForceKiller(self.global_state)
            case _:
                raise RuntimeError(f"Builder type {builder_type.name} not implemented")
