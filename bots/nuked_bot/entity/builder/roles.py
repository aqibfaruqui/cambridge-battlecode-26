from enum import IntEnum
from typing import Self

from cambc import Position


class BuilderType(IntEnum):
    RANDOM_EXPLORER = 0  # (-1, -1)
    FORCE_KILLER = 1  # ( 0, -1)
    BRIDGE_BUILDER = 2  # ( 1, -1)
    EXTRA_ROLE_3 = 3  # (-1,  0)
    EXTRA_ROLE_4 = 4  # ( 0,  0)
    EXTRA_ROLE_5 = 5  # ( 1,  0)
    EXTRA_ROLE_6 = 6  # (-1,  1)
    EXTRA_ROLE_7 = 7  # ( 1,  1)
    EXTRA_ROLE_8 = 8  # ( 1,  1)

    @property
    def offset(self) -> tuple[int, int]:
        """dx, dy from core position. Derived from value assuming 3x3 grid."""
        dx = (self.value % 3) - 1  # -1, 0, 1
        dy = (self.value // 3) - 1  # -1, 0, 1
        return dx, dy

    def position_from_core(self, core_pos: Position) -> Position:
        dx, dy = self.offset
        return Position(core_pos.x + dx, core_pos.y + dy)

    @classmethod
    def from_offset(cls, dx: int, dy: int) -> Self:
        val = (dy + 1) * 3 + (dx + 1)
        return cls(val)
