from enum import Enum, auto

from cambc import Controller, EntityType, Environment

_ENV_MAP = {
    Environment.EMPTY: 1,
    Environment.WALL: 2,
    Environment.ORE_TITANIUM: 3,
    Environment.ORE_AXIONITE: 4,
}

UNKNOWN = 0
TRAVERSABLE = 1
WALL = 2
ORE_TITANIUM = 3
ORE_AXIONITE = 4
CORE_OWN = 5
CORE_ENEMY = 6

_SYM_H = 1
_SYM_V = 2
_SYM_R = 4
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

_SINGLE_BIT = frozenset({_SYM_H, _SYM_V, _SYM_R})


class EnvironmentMap:
    __slots__ = (
        "_w",
        "_h",
        "_array",
        "_observed",
        "_cand",
        "_enemy_core_found",
        "_known_ti",
        "_known_ax",
    )

    def __init__(self, w: int, h: int):
        self._w = w
        self._h = h
        self._array = bytearray(w * h)
        self._observed = bytearray(w * h)
        self._cand: int = _SYM_ALL
        self._enemy_core_found = False
        self._known_ti: set[tuple[int, int]] = set()
        self._known_ax: set[tuple[int, int]] = set()

    def _set_tile(self, x: int, y: int, val: int, observed: bool = False) -> bool:
        idx = y * self._w + x
        old = self._array[idx]
        if old == val:
            if observed:
                self._observed[idx] = 1
            return False

        key = (x, y)
        if old == ORE_TITANIUM:
            self._known_ti.discard(key)
        elif old == ORE_AXIONITE:
            self._known_ax.discard(key)

        self._array[idx] = val
        if observed:
            self._observed[idx] = 1

        if val == ORE_TITANIUM:
            self._known_ti.add(key)
        elif val == ORE_AXIONITE:
            self._known_ax.add(key)

        return True

    def update(self, c: Controller) -> None:
        arr = self._array
        w = self._w
        wm1 = w - 1
        hm1 = self._h - 1

        env_map = _ENV_MAP
        get_tile_env = c.get_tile_env

        cand = self._cand
        resolved = cand in _SINGLE_BIT
        need_elim = not resolved

        # Core detection always allowed (no early disable)
        get_tile_building_id = c.get_tile_building_id
        get_entity_type = c.get_entity_type
        get_team = c.get_team
        my_team = c.get_team()
        entity_type_core = EntityType.CORE

        newly_seen_x: list[int] = []
        newly_seen_y: list[int] = []
        newly_seen_v: list[int] = []

        nsx = newly_seen_x.append
        nsy = newly_seen_y.append
        nsv = newly_seen_v.append

        has_new = False

        for tile in c.get_nearby_tiles():
            x, y = tile
            idx = y * w + x

            # Base terrain
            val = env_map[get_tile_env(tile)]

            # Core override
            bid = get_tile_building_id(tile)
            if bid is not None and get_entity_type(bid) is entity_type_core:
                if my_team == get_team(bid):
                    val = 5
                else:
                    val = 6
                    self._enemy_core_found = True

            if not self._set_tile(x, y, val, observed=True):
                continue

            nsx(x)
            nsy(y)
            nsv(val)
            has_new = True

        if not has_new:
            return

        # ---------- symmetry elimination ----------
        if need_elim:
            dead = 0
            sample_count = len(newly_seen_x)

            if cand & _SYM_H:
                for i in range(sample_count):
                    mirror = arr[newly_seen_y[i] * w + wm1 - newly_seen_x[i]]
                    if mirror != 0 and mirror != newly_seen_v[i]:
                        dead |= _SYM_H
                        break

            if cand & _SYM_V:
                for i in range(sample_count):
                    mirror = arr[(hm1 - newly_seen_y[i]) * w + newly_seen_x[i]]
                    if mirror != 0 and mirror != newly_seen_v[i]:
                        dead |= _SYM_V
                        break

            if cand & _SYM_R:
                for i in range(sample_count):
                    mirror = arr[(hm1 - newly_seen_y[i]) * w + wm1 - newly_seen_x[i]]
                    if mirror != 0 and mirror != newly_seen_v[i]:
                        dead |= _SYM_R
                        break

            if dead:
                cand &= ~dead
                self._cand = cand
                resolved = cand in _SINGLE_BIT

        # ---------- symmetry propagation ----------
        if resolved:
            sample_count = len(newly_seen_x)

            if cand == _SYM_H:
                for i in range(sample_count):
                    idx = newly_seen_y[i] * w + wm1 - newly_seen_x[i]
                    if arr[idx] == UNKNOWN:
                        self._set_tile(wm1 - newly_seen_x[i], newly_seen_y[i], newly_seen_v[i])

            elif cand == _SYM_V:
                for i in range(sample_count):
                    idx = (hm1 - newly_seen_y[i]) * w + newly_seen_x[i]
                    if arr[idx] == UNKNOWN:
                        self._set_tile(newly_seen_x[i], hm1 - newly_seen_y[i], newly_seen_v[i])

            else:  # rotational
                for i in range(sample_count):
                    idx = (hm1 - newly_seen_y[i]) * w + wm1 - newly_seen_x[i]
                    if arr[idx] == UNKNOWN:
                        self._set_tile(wm1 - newly_seen_x[i], hm1 - newly_seen_y[i], newly_seen_v[i])

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._w and 0 <= y < self._h

    def tile(self, x: int, y: int) -> int:
        return self._array[y * self._w + x]

    def is_unknown(self, x: int, y: int) -> bool:
        return self.tile(x, y) == UNKNOWN

    def is_frontier_passable(self, x: int, y: int) -> bool:
        return self.tile(x, y) in (TRAVERSABLE, CORE_OWN)

    def is_seek_candidate(self, x: int, y: int) -> bool:
        return self.tile(x, y) in (UNKNOWN, TRAVERSABLE, CORE_OWN)

    def nearest_known_titanium(
        self,
        origin,
        blocked: set[tuple[int, int]] | None = None,
        observed_only: bool = False,
    ):
        return self._nearest(origin, self._known_ti, blocked, observed_only=observed_only)

    def nearest_predicted_titanium(
        self,
        origin,
        blocked: set[tuple[int, int]] | None = None,
    ):
        return self._nearest(origin, self._known_ti, blocked, observed_only=False, predicted_only=True)

    def nearest_known_axionite(
        self, origin, blocked: set[tuple[int, int]] | None = None
    ):
        return self._nearest(origin, self._known_ax, blocked)

    def _nearest(
        self,
        origin,
        ore_set: set[tuple[int, int]],
        blocked: set[tuple[int, int]] | None = None,
        observed_only: bool = False,
        predicted_only: bool = False,
    ):
        best = None
        best_dist = float("inf")
        ox, oy = origin.x, origin.y
        observed = self._observed
        w = self._w
        for x, y in ore_set:
            if blocked is not None and (x, y) in blocked:
                continue
            seen = observed[y * w + x] != 0
            if observed_only and not seen:
                continue
            if predicted_only and seen:
                continue
            dist = (x - ox) * (x - ox) + (y - oy) * (y - oy)
            if dist < best_dist:
                best_dist = dist
                best = (x, y)
        return None if best is None else type(origin)(best[0], best[1])

    @property
    def symmetry_resolved(self) -> bool:
        return self._cand in _SINGLE_BIT

    @property
    def symmetry(self) -> Symmetry | None:
        return _FLAG_TO_SYM.get(self._cand)

    def __str__(self) -> str:
        w, h, arr = self._w, self._h, self._array
        char_map = ["U", ".", "█", "T", "A", "◎", "◉"]
        grid = "\n".join(
            "".join(char_map[arr[y * w + x]] for x in range(w)) for y in range(h)
        )
        sym = self.symmetry
        tag = sym.name if sym else f"candidates={bin(self._cand)}"
        return f"EnvironmentMap({w}x{h}, {tag})\n{grid}"
