from typing import Generic, TypeVar

from action.interface import Action, TaskResult
from cambc import Controller

T = TypeVar("T")


class SetState(Action, Generic[T]):
    """Instant action that sets an attribute on a target object."""

    def __init__(self, target: object, attr: str, value: T):
        self.target = target
        self.attr = attr
        self.value = value

    def run(self, _: Controller) -> TaskResult:
        setattr(self.target, self.attr, self.value)
        return TaskResult.SUCCESS

    def __str__(self) -> str:
        return f"SetState({self.attr}={self.value})"
