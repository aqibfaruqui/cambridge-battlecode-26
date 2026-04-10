from enum import IntEnum

from cambc import Controller


class TaskResult(IntEnum):
    SUCCESS = 0
    INCOMPLETE = 1
    FAILURE = 2


class Action:
    """A finite task that completes or fails."""

    interruptible = True

    def can_run(self, _: Controller) -> bool:
        """Precondition check. Called by run_actions before run().
        Default: raises exception. You must override to assert adjacency,
        affordability, etc."""
        raise NotImplementedError("You must implement the can_run function.")

    def run(self, c: Controller) -> TaskResult:
        raise NotImplementedError("You must implement the run function.")

    def __str__(self) -> str:
        return self.__class__.__name__


def run_actions(
    c: Controller, actions: list[Action], skip_can_run: bool = False
) -> TaskResult:
    """Run top of stack. If can_run() fails, return INCOMPLETE.
    On SUCCESS, pop and continue. On FAILURE, pop and return.
    On INCOMPLETE, keep and return."""
    first = True
    while actions:
        top = actions[-1]

        print("Executing action stack: ")
        for action in actions[:-1]:
            print(f"{action}")

        if first and skip_can_run:
            first = False
        elif not top.can_run(c):
            return TaskResult.INCOMPLETE

        result = top.run(c)
        if result == TaskResult.FAILURE:
            actions.pop()
            return TaskResult.FAILURE
        if result == TaskResult.SUCCESS:
            actions.pop()
            continue
        return TaskResult.INCOMPLETE

    return TaskResult.SUCCESS


class Behaviour:
    """Perpetual role controller. Owns an action stack and provides
    structured hooks for interrupts, phase transitions, and idle seeding."""

    def __init__(self):
        self.actions: list[Action] = []

    def tick(self, c: Controller) -> None:
        """Called once per turn by the entity dispatcher."""
        if not self.actions or all(a.interruptible for a in self.actions):
            self.check_interrupts(c)
        self.check_transitions(c)

        if not self.actions:
            self.idle(c)

        run_actions(c, self.actions)

    def check_interrupts(self, c: Controller) -> None:
        pass

    def check_transitions(self, c: Controller) -> None:
        pass

    def idle(self, c: Controller) -> None:
        pass
