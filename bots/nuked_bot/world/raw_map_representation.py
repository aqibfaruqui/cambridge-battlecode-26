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
    __slots__ = ("c", "_w", "_h", "_array")

    def __init__(self, c: Controller):
        self.c = c
        self._w = c.get_map_width()
        self._h = c.get_map_height()
        self._array = bytearray(self._w * self._h)

    def _idx(self, pos: Position) -> int:
        return pos.y * self._w + pos.x

    def at(self, pos: Position) -> CustomEnv:
        return CustomEnv(self._array[self._idx(pos)])

    def set(self, pos: Position, env: CustomEnv) -> None:
        self._array[self._idx(pos)] = env

    def at_raw(self, x: int, y: int) -> int:
        return self._array[y * self._w + x]

    def set_raw(self, x: int, y: int, value: int) -> None:
        self._array[y * self._w + x] = value

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    # ---- rendering ----
    def __str__(self) -> str:
        w = self._w
        h = self._h
        arr = self._array
        cmap = CHAR_MAP

        rows = []
        for y in range(h):
            base = y * w
            rows.append("".join(cmap[arr[base + x]] for x in range(w)))
        return "\n".join(rows)

    def __repr__(self) -> str:
        return f"EnvironmentMap({self._w}x{self._h})"
