from cambc import Controller, Position, EntityType, Environment
from enum import IntEnum


class CustomEnv(IntEnum):
    EMPTY = 0
    WALL = 1
    ORE_TITANIUM = 2
    ORE_AXIONITE = 3
    TEAM_CORE = 4
    ENEMY_CORE = 5


_ENV_MAP = {
    Environment.EMPTY: 0,
    Environment.WALL: 1,
    Environment.ORE_TITANIUM: 2,
    Environment.ORE_AXIONITE: 3,
}

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

    def update(self, c: Controller) -> None:
        arr = self._array
        w = self._w
        get_tile_env = c.get_tile_env
        get_tile_building_id = c.get_tile_building_id
        get_entity_type = c.get_entity_type
        get_team = c.get_team

        for tile in c.get_nearby_tiles():
            x, y = tile
            idx = y * w + x
            bid = get_tile_building_id(tile)
            if bid is not None and get_entity_type(bid) == EntityType.CORE:
                arr[idx] = 4 if get_team() == get_team(bid) else 5
            else:
                arr[idx] = _ENV_MAP[get_tile_env(tile)]

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
