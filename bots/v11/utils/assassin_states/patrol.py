from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller

if TYPE_CHECKING:
    from builders.assassin import Assassin


def patrol(self: Assassin, c: Controller) -> None:
    """Out of scope — once the gunner is built, the assassin idles for now."""
    return
