from enum import Enum, auto

from cambc import Controller, EntityType, Environment, Position

# Bind enum members to module-local names so the hot loop can use `is` checks
# instead of dict lookups (which call enum.__hash__ — measurable in the
# profile at ~388k calls/run).
_ENV_EMPTY = Environment.EMPTY
_ENV_WALL = Environment.WALL
_ENV_ORE_TI = Environment.ORE_TITANIUM
# ORE_AXIONITE handled via the else branch in update().

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
        observed = self._observed
        known_ti = self._known_ti
        known_ax = self._known_ax
        w = self._w
        wm1 = w - 1
        hm1 = self._h - 1

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
        env_empty = _ENV_EMPTY
        env_wall = _ENV_WALL
        env_ti = _ENV_ORE_TI
        # any other Environment value falls through to ORE_AXIONITE (val=4)

        # Single packed list keeps newly-observed-changed cells: alternating
        # idx, val pairs. Halves the per-tile bookkeeping vs. three parallel
        # lists, and the symmetry sections recompute x,y from idx (cheap).
        newly: list[int] = []
        nappend = newly.append

        for tile in c.get_nearby_tiles():
            x = tile.x
            y = tile.y
            idx = y * w + x

            # Base terrain via `is` chain — avoids enum.__hash__/dict lookup.
            e = get_tile_env(tile)
            if e is env_empty:
                val = 1
            elif e is env_wall:
                val = 2
            elif e is env_ti:
                val = 3
            else:
                val = 4

            # Core override
            bid = get_tile_building_id(tile)
            if bid is not None and get_entity_type(bid) is entity_type_core:
                if my_team == get_team(bid):
                    val = 5
                else:
                    val = 6
                    self._enemy_core_found = True

            observed[idx] = 1
            old = arr[idx]
            if old == val:
                continue

            # Inlined ore-set bookkeeping.
            if old == 3:
                known_ti.discard((x, y))
            elif old == 4:
                known_ax.discard((x, y))
            arr[idx] = val
            if val == 3:
                known_ti.add((x, y))
            elif val == 4:
                known_ax.add((x, y))

            nappend(idx)
            nappend(val)

        if not newly:
            return

        # ---------- symmetry elimination ----------
        if need_elim:
            dead = 0
            n_pairs = len(newly)

            if cand & _SYM_H:
                i = 0
                while i < n_pairs:
                    idx = newly[i]
                    v = newly[i + 1]
                    mirror = arr[(idx // w) * w + wm1 - (idx % w)]
                    if mirror != 0 and mirror != v:
                        dead |= _SYM_H
                        break
                    i += 2

            if cand & _SYM_V:
                i = 0
                while i < n_pairs:
                    idx = newly[i]
                    v = newly[i + 1]
                    mirror = arr[(hm1 - idx // w) * w + (idx % w)]
                    if mirror != 0 and mirror != v:
                        dead |= _SYM_V
                        break
                    i += 2

            if cand & _SYM_R:
                i = 0
                while i < n_pairs:
                    idx = newly[i]
                    v = newly[i + 1]
                    mirror = arr[(hm1 - idx // w) * w + wm1 - (idx % w)]
                    if mirror != 0 and mirror != v:
                        dead |= _SYM_R
                        break
                    i += 2

            if dead:
                cand &= ~dead
                self._cand = cand
                resolved = cand in _SINGLE_BIT

        # ---------- symmetry propagation ----------
        if resolved:
            n_pairs = len(newly)
            if cand == _SYM_H:
                i = 0
                while i < n_pairs:
                    idx = newly[i]
                    v = newly[i + 1]
                    x = idx % w
                    y = idx // w
                    midx = y * w + wm1 - x
                    if arr[midx] == UNKNOWN:
                        self._set_tile(wm1 - x, y, v)
                    i += 2
            elif cand == _SYM_V:
                i = 0
                while i < n_pairs:
                    idx = newly[i]
                    v = newly[i + 1]
                    x = idx % w
                    y = idx // w
                    midx = (hm1 - y) * w + x
                    if arr[midx] == UNKNOWN:
                        self._set_tile(x, hm1 - y, v)
                    i += 2
            else:  # rotational
                i = 0
                while i < n_pairs:
                    idx = newly[i]
                    v = newly[i + 1]
                    x = idx % w
                    y = idx // w
                    midx = (hm1 - y) * w + wm1 - x
                    if arr[midx] == UNKNOWN:
                        self._set_tile(wm1 - x, hm1 - y, v)
                    i += 2

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

    @property
    def assumed_symmetry(self) -> Symmetry | None:
        """Resolved symmetry if known, else ROTATIONAL while it's still a live candidate.

        Lets navigation commit to a rotational enemy-core guess before elimination
        completes — gives up (returns None) once the map disproves rotational.
        """
        resolved = _FLAG_TO_SYM.get(self._cand)
        if resolved is not None:
            return resolved
        if self._cand & _SYM_R:
            return Symmetry.ROTATIONAL
        return None

    def force_symmetry(self, sym: Symmetry) -> None:
        """Lock symmetry and mirror all observed tiles into their unknown counterparts.

        Used when another bot broadcasts a resolved symmetry — we trust it and
        immediately fill in the derived half of the map so D* planners (which
        diff against EnvironmentMap on notify_map_changes) see the updated
        terrain on their next step.
        """
        flag_for = {
            Symmetry.HORIZONTAL: _SYM_H,
            Symmetry.VERTICAL: _SYM_V,
            Symmetry.ROTATIONAL: _SYM_R,
        }[sym]
        if self._cand == flag_for:
            return
        self._cand = flag_for

        arr = self._array
        observed = self._observed
        w = self._w
        h = self._h
        wm1 = w - 1
        hm1 = h - 1

        for y in range(h):
            for x in range(w):
                idx = y * w + x
                if observed[idx] == 0:
                    continue
                val = arr[idx]
                if val == UNKNOWN:
                    continue
                if sym is Symmetry.HORIZONTAL:
                    mx, my = wm1 - x, y
                elif sym is Symmetry.VERTICAL:
                    mx, my = x, hm1 - y
                else:
                    mx, my = wm1 - x, hm1 - y
                if arr[my * w + mx] == UNKNOWN:
                    self._set_tile(mx, my, val)

    def enemy_core_centre(self, own_core: Position) -> Position | None:
        """Centre of the enemy 3x3 core deduced from resolved symmetry, or None."""
        return self._core_centre_for(_FLAG_TO_SYM.get(self._cand), own_core)

    def assumed_enemy_core_centre(self, own_core: Position) -> Position | None:
        """Centre deduced from `assumed_symmetry` (rotational fallback while live)."""
        return self._core_centre_for(self.assumed_symmetry, own_core)

    def _core_centre_for(self, sym: "Symmetry | None", own_core: Position) -> Position | None:
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
