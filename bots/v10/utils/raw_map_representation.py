from enum import Enum, auto

from cambc import Controller, EntityType, Environment, Position

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


def _write_tile(arr, ti_set, ax_set, idx, x, y, val):
    old = arr[idx]
    if old == val:
        return
    if old == ORE_TITANIUM:
        ti_set.discard((x, y))
    elif old == ORE_AXIONITE:
        ax_set.discard((x, y))
    arr[idx] = val
    if val == ORE_TITANIUM:
        ti_set.add((x, y))
    elif val == ORE_AXIONITE:
        ax_set.add((x, y))


class EnvironmentMap:
    __slots__ = (
        "_w",
        "_h",
        "_array_h",
        "_array_v",
        "_array_r",
        # Active hypothesis aliases. _array / _known_ti / _known_ax always
        # point at one of the three per-symmetry buffers above. Initial
        # hypothesis is rotational; _select_active() rebinds them when
        # candidates are eliminated.
        "_array",
        "_known_ti",
        "_known_ax",
        "_observed",
        "_cand",
        "_enemy_core_found",
        "_known_ti_h",
        "_known_ti_v",
        "_known_ti_r",
        "_known_ax_h",
        "_known_ax_v",
        "_known_ax_r",
    )

    def __init__(self, w: int, h: int):
        self._w = w
        self._h = h
        size = w * h
        self._array_h = bytearray(size)
        self._array_v = bytearray(size)
        self._array_r = bytearray(size)
        self._observed = bytearray(size)
        self._cand: int = _SYM_ALL
        self._enemy_core_found = False
        self._known_ti_h: set[tuple[int, int]] = set()
        self._known_ti_v: set[tuple[int, int]] = set()
        self._known_ti_r: set[tuple[int, int]] = set()
        self._known_ax_h: set[tuple[int, int]] = set()
        self._known_ax_v: set[tuple[int, int]] = set()
        self._known_ax_r: set[tuple[int, int]] = set()
        # Default to rotational hypothesis until candidates whittle down.
        self._array = self._array_r
        self._known_ti = self._known_ti_r
        self._known_ax = self._known_ax_r

    def _select_active(self) -> None:
        cand = self._cand
        if cand & _SYM_R:
            self._array = self._array_r
            self._known_ti = self._known_ti_r
            self._known_ax = self._known_ax_r
        elif cand & _SYM_H:
            self._array = self._array_h
            self._known_ti = self._known_ti_h
            self._known_ax = self._known_ax_h
        else:
            self._array = self._array_v
            self._known_ti = self._known_ti_v
            self._known_ax = self._known_ax_v

    def _set_observed(self, x: int, y: int, val: int) -> None:
        w = self._w
        idx = y * w + x
        self._observed[idx] = 1

        write = _write_tile
        arr_h = self._array_h
        arr_v = self._array_v
        arr_r = self._array_r
        ti_h = self._known_ti_h
        ti_v = self._known_ti_v
        ti_r = self._known_ti_r
        ax_h = self._known_ax_h
        ax_v = self._known_ax_v
        ax_r = self._known_ax_r

        # Direct writes — observed value goes into all three hypotheses.
        write(arr_h, ti_h, ax_h, idx, x, y, val)
        write(arr_v, ti_v, ax_v, idx, x, y, val)
        write(arr_r, ti_r, ax_r, idx, x, y, val)

        # Mirror writes — only into unobserved cells (observation > prediction).
        observed = self._observed
        wm1 = w - 1
        hm1 = self._h - 1

        mh_x = wm1 - x
        mh_idx = y * w + mh_x
        if not observed[mh_idx]:
            write(arr_h, ti_h, ax_h, mh_idx, mh_x, y, val)

        mv_y = hm1 - y
        mv_idx = mv_y * w + x
        if not observed[mv_idx]:
            write(arr_v, ti_v, ax_v, mv_idx, x, mv_y, val)

        mr_idx = mv_y * w + mh_x
        if not observed[mr_idx]:
            write(arr_r, ti_r, ax_r, mr_idx, mh_x, mv_y, val)

    def update(self, c: Controller) -> None:
        w = self._w
        wm1 = w - 1
        hm1 = self._h - 1

        env_map = _ENV_MAP
        get_tile_env = c.get_tile_env

        cand = self._cand
        need_elim = cand not in _SINGLE_BIT

        get_tile_building_id = c.get_tile_building_id
        get_entity_type = c.get_entity_type
        get_team = c.get_team
        my_team = c.get_team()
        entity_type_core = EntityType.CORE

        observed = self._observed
        # All three arrays agree at observed positions, so any one is fine
        # for elimination checks.
        arr_obs = self._array_r

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

            # Terrain and cores are static — already-observed tiles carry
            # nothing new to integrate.
            if observed[idx]:
                continue

            val = env_map[get_tile_env(tile)]

            bid = get_tile_building_id(tile)
            if bid is not None and get_entity_type(bid) is entity_type_core:
                if my_team == get_team(bid):
                    val = 5
                else:
                    val = 6
                    self._enemy_core_found = True

            self._set_observed(x, y, val)

            nsx(x)
            nsy(y)
            nsv(val)
            has_new = True

        if not has_new:
            return

        if need_elim:
            dead = 0
            sample_count = len(newly_seen_x)

            if cand & _SYM_H:
                for i in range(sample_count):
                    midx = newly_seen_y[i] * w + wm1 - newly_seen_x[i]
                    if observed[midx] and arr_obs[midx] != newly_seen_v[i]:
                        dead |= _SYM_H
                        break

            if cand & _SYM_V:
                for i in range(sample_count):
                    midx = (hm1 - newly_seen_y[i]) * w + newly_seen_x[i]
                    if observed[midx] and arr_obs[midx] != newly_seen_v[i]:
                        dead |= _SYM_V
                        break

            if cand & _SYM_R:
                for i in range(sample_count):
                    midx = (hm1 - newly_seen_y[i]) * w + wm1 - newly_seen_x[i]
                    if observed[midx] and arr_obs[midx] != newly_seen_v[i]:
                        dead |= _SYM_R
                        break

            if dead:
                self._cand = cand & ~dead
                self._select_active()

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
        return self._array[y * self._w + x] == UNKNOWN

    def is_frontier_passable(self, x: int, y: int) -> bool:
        v = self._array[y * self._w + x]
        return v == TRAVERSABLE or v == CORE_OWN

    def is_seek_candidate(self, x: int, y: int) -> bool:
        v = self._array[y * self._w + x]
        return v == UNKNOWN or v == TRAVERSABLE or v == CORE_OWN

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

    def enemy_core_centre(self, own_core: Position) -> Position | None:
        """Centre of the enemy 3x3 core deduced from resolved symmetry, or None."""
        sym = _FLAG_TO_SYM.get(self._cand)
        if sym is None:
            return None
        wm1 = self._w - 1
        hm1 = self._h - 1
        cx, cy = own_core.x, own_core.y
        if sym is Symmetry.ROTATIONAL:
            return Position(wm1 - cx, hm1 - cy)
        if sym is Symmetry.HORIZONTAL:
            return Position(wm1 - cx, cy)
        return Position(cx, hm1 - cy)

    def __str__(self) -> str:
        w, h, arr = self._w, self._h, self._array
        char_map = ["U", ".", "█", "T", "A", "◎", "◉"]
        grid = "\n".join(
            "".join(char_map[arr[y * w + x]] for x in range(w)) for y in range(h)
        )
        sym = self.symmetry
        tag = sym.name if sym else f"candidates={bin(self._cand)}"
        return f"EnvironmentMap({w}x{h}, {tag})\n{grid}"
