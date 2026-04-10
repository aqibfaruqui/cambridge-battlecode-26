from enum import Enum, auto
from cambc import Controller, EntityType, Environment

_ENV_MAP = {
    Environment.EMPTY: 0,
    Environment.WALL: 1,
    Environment.ORE_TITANIUM: 2,
    Environment.ORE_AXIONITE: 3,
}

# Bit flags for symmetry candidates
_SYM_H = 1  # horizontal
_SYM_V = 2  # vertical
_SYM_R = 4  # rotational
_SYM_ALL = _SYM_H | _SYM_V | _SYM_R


class Symmetry(Enum):
    HORIZONTAL = auto()
    VERTICAL = auto()
    ROTATIONAL = auto()


_FLAG_TO_SYM = {
    _SYM_H: Symmetry.HORIZONTAL,
    _SYM_V: Symmetry.VERTICAL,
    _SYM_R: Symmetry.ROTATIONAL,
}

# popcount-style check: is exactly one bit set?
_SINGLE_BIT = frozenset({_SYM_H, _SYM_V, _SYM_R})


class EnvironmentMap:
    __slots__ = ("_w", "_h", "_array", "_cand")

    def __init__(self, w: int, h: int):
        self._w = w
        self._h = h
        self._array = bytearray(w * h)
        self._cand: int = _SYM_ALL  # bitflag

    def update(self, c: Controller) -> None:
        """Update the state of the map given a controller"""
        arr = self._array
        w = self._w
        h = self._h
        wm1 = w - 1
        hm1 = h - 1
        env_map = _ENV_MAP
        get_tile_env = c.get_tile_env
        get_tile_building_id = c.get_tile_building_id
        get_entity_type = c.get_entity_type
        my_team = c.get_team()
        get_team = c.get_team
        cand = self._cand
        resolved = cand in _SINGLE_BIT
        need_elim = not resolved

        newly_seen_x: list[int] = []
        newly_seen_y: list[int] = []
        newly_seen_v: list[int] = []
        ns_append_x = newly_seen_x.append
        ns_append_y = newly_seen_y.append
        ns_append_v = newly_seen_v.append
        has_new = False

        EntityType_CORE = EntityType.CORE

        for tile in c.get_nearby_tiles():
            x, y = tile
            idx = y * w + x
            bid = get_tile_building_id(tile)
            if bid is not None and get_entity_type(bid) is EntityType_CORE:
                val = 4 if my_team == get_team(bid) else 5
            else:
                val = env_map[get_tile_env(tile)]
            if val != 0 and arr[idx] == 0:
                ns_append_x(x)
                ns_append_y(y)
                ns_append_v(val)
                has_new = True
            arr[idx] = val

        if not has_new:
            return

        if need_elim:
            dead = 0
            n = len(newly_seen_x)
            if cand & _SYM_H and not (dead & _SYM_H):
                for i in range(n):
                    mv = arr[newly_seen_y[i] * w + wm1 - newly_seen_x[i]]
                    if mv != 0 and mv != newly_seen_v[i]:
                        dead |= _SYM_H
                        break
            if cand & _SYM_V and not (dead & _SYM_V):
                for i in range(n):
                    mv = arr[(hm1 - newly_seen_y[i]) * w + newly_seen_x[i]]
                    if mv != 0 and mv != newly_seen_v[i]:
                        dead |= _SYM_V
                        break
            if cand & _SYM_R and not (dead & _SYM_R):
                for i in range(n):
                    mv = arr[(hm1 - newly_seen_y[i]) * w + wm1 - newly_seen_x[i]]
                    if mv != 0 and mv != newly_seen_v[i]:
                        dead |= _SYM_R
                        break
            if dead:
                cand &= ~dead
                self._cand = cand
                resolved = cand in _SINGLE_BIT

        if resolved:
            # Inline mirror fill
            n = len(newly_seen_x)
            if cand == _SYM_H:
                for i in range(n):
                    midx = newly_seen_y[i] * w + wm1 - newly_seen_x[i]
                    if arr[midx] == 0:
                        arr[midx] = newly_seen_v[i]
            elif cand == _SYM_V:
                for i in range(n):
                    midx = (hm1 - newly_seen_y[i]) * w + newly_seen_x[i]
                    if arr[midx] == 0:
                        arr[midx] = newly_seen_v[i]
            else:  # _SYM_R
                for i in range(n):
                    midx = (hm1 - newly_seen_y[i]) * w + wm1 - newly_seen_x[i]
                    if arr[midx] == 0:
                        arr[midx] = newly_seen_v[i]

    @property
    def symmetry_resolved(self) -> bool:
        return self._cand in _SINGLE_BIT

    @property
    def symmetry(self) -> Symmetry | None:
        return _FLAG_TO_SYM.get(self._cand)

    def __str__(self) -> str:
        w, h, arr = self._w, self._h, self._array
        char_map = [".", "█", "T", "A", "◎", "◉"]
        grid = "\n".join(
            "".join(char_map[arr[y * w + x]] for x in range(w)) for y in range(h)
        )
        sym = self.symmetry
        tag = sym.name if sym else f"candidates={bin(self._cand)}"
        return f"EnvironmentMap({w}x{h}, {tag})\n{grid}"
