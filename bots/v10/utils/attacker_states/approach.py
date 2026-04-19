from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller

if TYPE_CHECKING:
    from builders.attacker_revamped import AttackerRevamped


def _approach(self: AttackerRevamped, c: Controller) -> None:
    """Navigate D* Lite all the way onto the target conveyor tile.

    Firing requires standing on the tile, so this state only transitions to
    REPLACE once the attacker has actually stepped onto the target.
    """
    assert self.target_conveyor is not None
    self.target_pos = self.target_conveyor
    if self.current_pos == self.target_conveyor:
        self.state = type(self.state).REPLACE
        return
    self._search(c, self.target_conveyor)
