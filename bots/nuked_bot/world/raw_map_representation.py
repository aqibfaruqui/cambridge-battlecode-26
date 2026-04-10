from cambc import Controller, Position
from enum import IntEnum


class CustomEnv(IntEnum):
    EMPTY = 0
    WALL = 1
    ORE_TITANIUM = 2
    ORE_AXIONITE = 3
    TEAM_CORE = 4
    ENEMY_CORE = 5


CHAR_MAP = [".", "█", "T", "A", "◎", "◉"]


class EnvironmentMap:
    __slots__ = ("_w", "_h", "_array")

    def __init__(self, w: int, h: int):
        self._w = w
        self._h = h
        self._array = bytearray(w * h)

    def at_raw(self, x: int, y: int) -> int:
        return self._array[y * self._w + x]

    def set_raw(self, x: int, y: int, v: int) -> None:
        self._array[y * self._w + x] = v

    def __str__(self) -> str:
        w = self._w
        h = self._h
        arr = self._array
        cmap = CHAR_MAP

        rows = []
        for y in range(h):
            base = y * w
            row = [""] * w
            for x in range(w):
                row[x] = cmap[arr[base + x]]
            rows.append("".join(row))
        return "\n".join(rows)

    def __repr__(self) -> str:
        return f"EnvironmentMap({self._w}x{self._h})"
