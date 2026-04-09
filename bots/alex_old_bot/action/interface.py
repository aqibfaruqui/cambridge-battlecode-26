from enum import IntEnum

from cambc import Controller


class TaskResult(IntEnum):
    SUCCESS = 0
    INCOMPLETE = 1
    FAILURE = 2


class Action:
    """A finite task that completes or fails."""

    def can_run(self, _: Controller) -> bool:
        """Precondition check. Called by run_actions before run().
        Default: True. Override to assert adjacency, affordability, etc."""
        return True

    def run(self, c: Controller) -> TaskResult:
        raise NotImplementedError

    def __str__(self) -> str:
        return self.__class__.__name__


def run_actions(c: Controller, actions: list[Action], skip_can_run: bool = False) -> TaskResult:
    """Run top of stack. If can_run() fails, pop with INCOMPLETE.
    On SUCCESS/FAILURE, pop. On INCOMPLETE, keep.
    skip_can_run: skip the can_run check on the first action (caller already verified)."""
    first = True
    while actions:
        top = actions[-1]
        if first and skip_can_run:
            first = False
        elif not top.can_run(c):
            print(f"Action {top.__class__.__name__} cannot run, waiting")
            return TaskResult.INCOMPLETE

        result = top.run(c)
        if result == TaskResult.FAILURE:
            print(f"Action {top.__class__.__name__} failed, popping")
            actions.pop()
            return TaskResult.FAILURE
        if result == TaskResult.SUCCESS:
            print(f"Action {top.__class__.__name__} succeeded, popping")
            actions.pop()
            continue
        print(f"Action {top.__class__.__name__} incomplete, keeping")

    print("All actions completed, returning success")
    return TaskResult.SUCCESS


def print_action_stack(actions: list[Action]) -> None:
    print("Action stack:")
    for action in actions:
        print(f"  {action}")


class Behaviour:
    """Perpetual role controller. Owns an action stack and provides
    structured hooks for interrupts, phase transitions, and idle seeding."""

    def __init__(self):
        self.actions: list[Action] = []

    def tick(self, c: Controller) -> None:
        """Called once per turn by the entity dispatcher."""
        print_action_stack(self.actions)
        self.check_interrupts(c)
        self.check_transitions(c)

        if not self.actions:
            self.idle(c)

        run_actions(c, self.actions)

    def check_interrupts(self, c: Controller) -> None:
        """Scan for conditions and push high-priority actions onto the stack.
        Runs every tick BEFORE the current action. Override per-behaviour.
        Default: no-op."""
        pass

    def check_transitions(self, c: Controller) -> None:
        """Detect phase changes and replace the action stack.
        Runs every tick after interrupts. Override per-behaviour.
        Default: no-op."""
        pass

    def idle(self, c: Controller) -> None:
        """Seed the action stack when it's empty.
        Override per-behaviour. Default: no-op."""
        pass
