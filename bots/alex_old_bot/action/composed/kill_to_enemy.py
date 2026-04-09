from action.interface import Action, TaskResult, run_actions
from action.navigation import Goto
from world.state import GlobalState
from cambc import Controller


class KillToEnemy(Action):
    def __init__(self, global_state: GlobalState):
        super().__init__()
        self.global_state = global_state

        self._actions: list[Action] = []

    def can_run(c: Controller) -> bool:
        pass

    def run(c: Controller) -> TaskResult:
        pass
