from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller

from utils.attacker_states.state import AttackState

if TYPE_CHECKING:
    from builders.attacker import Attacker


def _approach(self: Attacker, c: Controller) -> None:
    assert self.target_conveyor is not None
    self.target_pos = self.target_conveyor
    if self.current_pos == self.target_conveyor:
        self.state = AttackState.REPLACE
        return
    self._search(c, self.target_conveyor)
