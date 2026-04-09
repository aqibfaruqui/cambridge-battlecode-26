from cambc import EntityType
import grid
from action.interface import Action, TaskResult, run_actions
from action.build import BuildHarvester, BuildMarker
from action.navigation import Goto
from world.comms.for_builder_bot import BuilderBotMessages
from cambc import Position, Controller
from world.state import GlobalState


class GotoPlaceHarvester(Action):
    def __init__(self, global_state: GlobalState, c: Controller, target: Position):
        super().__init__()
        self.target = target
        adjacent: list[Position] = grid.adjacent_positions(c, target)
        adjacent.sort(key=lambda p: p.distance_squared(target))
        self.actions = [
            BuildHarvester(
                global_state,
                target,
                wait_for_resources=(10, 0),
                destroy=[
                    EntityType.ROAD,
                    EntityType.MARKER,
                    EntityType.LAUNCHER,
                    EntityType.BARRIER,
                ],
            ),
            Goto(global_state, adjacent),
            BuildMarker(
                global_state,
                message=BuilderBotMessages.encode_claim_ore(target),
            ),
        ]

    def can_run(self, c: Controller) -> bool:
        if not self.actions:
            return True

        return self.actions[-1].can_run(c)

    def run(self, c: Controller) -> TaskResult:
        return run_actions(c, self.actions)

    def __str__(self) -> str:
        return f"GotoPlaceHarvester(target={self.target})"
