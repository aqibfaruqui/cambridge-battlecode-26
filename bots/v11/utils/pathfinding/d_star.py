import heapq
import math
from typing import List, Tuple

from cambc import Direction

from utils.map.raw_map_representation import EnvironmentMap

_INF = float("inf")
_SQRT2 = math.sqrt(2)

_NEIGHBOURS = (
    (0, -1, 1.0, Direction.NORTH),
    (1, -1, _SQRT2, Direction.NORTHEAST),
    (1, 0, 1.0, Direction.EAST),
    (1, 1, _SQRT2, Direction.SOUTHEAST),
    (0, 1, 1.0, Direction.SOUTH),
    (-1, 1, _SQRT2, Direction.SOUTHWEST),
    (-1, 0, 1.0, Direction.WEST),
    (-1, -1, _SQRT2, Direction.NORTHWEST),
)

_UNKNOWN = 0
_WALL = 2
_ORE_TITANIUM = 3
_ORE_AXIONITE = 4
_ENEMY_CORE = 6
_DEFAULT_BLOCK_MASK = (
    (1 << _UNKNOWN)
    | (1 << _WALL)
    | (1 << _ORE_TITANIUM)
    | (1 << _ORE_AXIONITE)
    | (1 << _ENEMY_CORE)
)
_RETURN_BLOCK_MASK = (
    (1 << _WALL)
    | (1 << _ORE_TITANIUM)
    | (1 << _ORE_AXIONITE)
    | (1 << _ENEMY_CORE)
)
# Like _RETURN_BLOCK_MASK but allows UNKNOWN tiles — lets the seek planner
# route through unexplored space. Axionite is blocked because builders
# cannot physically step on ore tiles.
_SEEK_BLOCK_MASK = (
    (1 << _WALL)
    | (1 << _ORE_TITANIUM)
    | (1 << _ORE_AXIONITE)
    | (1 << _ENEMY_CORE)
)

# Jump-edge offsets: (dx, dy) pairs with 2 < dx*dx + dy*dy <= 9.
# Jumps conceptually bypass any tiles between source and destination; the
# endpoint is still validated against block_mask and _dynamic_blocked.
_JUMP_OFFSETS = (
    # dist_sq = 5
    (-2, -1), (-2,  1), ( 2, -1), ( 2,  1),
    (-1, -2), ( 1, -2), (-1,  2), ( 1,  2),
    # dist_sq = 8
    (-2, -2), ( 2, -2), (-2,  2), ( 2,  2),
    # dist_sq = 9
    (-3,  0), ( 3,  0), ( 0, -3), ( 0,  3),
)


class DStarLite:
    __slots__ = (
        "_env",
        "_w",
        "_h",
        "_n",
        "_g",
        "_rhs",
        "_open",
        "_in_open",
        "_km",
        "_start",
        "_start_x",
        "_start_y",
        "_goal",
        "_last",
        "_snapshot",
        "_block_mask",
        "_dynamic_blocked",
        "_unknown_cost",
        "_allow_jumps",
        "_jump_cost",
    )

    def __init__(
        self,
        env: EnvironmentMap,
        goal_x: int,
        goal_y: int,
        *,
        block_mask: int = _DEFAULT_BLOCK_MASK,
        unknown_cost: float = 1.0,
        allow_jumps: bool = False,
        jump_cost: float = 5.0,
    ):
        self._env = env
        self._w = env._w
        self._h = env._h
        self._n = self._w * self._h
        self._block_mask = block_mask

        self._g = [_INF] * self._n
        self._rhs = [_INF] * self._n

        self._open: List[Tuple[Tuple[float, float], int]] = []
        self._in_open = [False] * self._n

        self._km = 0.0

        self._goal = self._to_idx(goal_x, goal_y)
        self._start = self._goal
        self._start_x = goal_x
        self._start_y = goal_y
        self._last = self._start

        self._rhs[self._goal] = 0.0
        self._enqueue(self._goal)

        self._snapshot = bytearray(env._array)
        self._dynamic_blocked: set[int] = set()
        self._unknown_cost = unknown_cost
        self._allow_jumps = allow_jumps
        self._jump_cost = jump_cost

    # ---------- Public API ----------

    def set_goal(self, gx: int, gy: int) -> None:
        self.__init__(
            self._env,
            gx,
            gy,
            block_mask=self._block_mask,
            unknown_cost=self._unknown_cost,
            allow_jumps=self._allow_jumps,
            jump_cost=self._jump_cost,
        )

    def set_position(self, sx: int, sy: int) -> None:
        # Heuristic(_last, new_start) inlined using cached coords.
        dx = abs(self._start_x - sx)
        dy = abs(self._start_y - sy)
        self._km += (dx + dy) + (_SQRT2 - 2) * (dx if dx < dy else dy)
        new_start = sy * self._w + sx
        self._last = new_start
        self._start = new_start
        self._start_x = sx
        self._start_y = sy

    def notify_map_changes(self) -> bool:
        arr = self._env._array
        snapshot = self._snapshot

        # Fast path: bytearray equality is a single C memcmp.
        if arr == snapshot:
            return False

        w = self._w
        h = self._h
        n = self._n
        recompute = self._recompute_rhs

        i = 0
        while i < n:
            if arr[i] != snapshot[i]:
                snapshot[i] = arr[i]

                x = i % w
                y = i // w
                # Inlined: for pred in _pred(i): recompute(pred)
                if y > 0:
                    recompute(i - w)
                    if x > 0:
                        recompute(i - w - 1)
                    if x < w - 1:
                        recompute(i - w + 1)
                if y < h - 1:
                    recompute(i + w)
                    if x > 0:
                        recompute(i + w - 1)
                    if x < w - 1:
                        recompute(i + w + 1)
                if x > 0:
                    recompute(i - 1)
                if x < w - 1:
                    recompute(i + 1)

                recompute(i)
            i += 1

        self._compute_shortest_path()
        return True

    def set_dynamic_blockers(self, blocked_xy: list[tuple[int, int]]) -> bool:
        new_blocked: set[int] = set()
        for x, y in blocked_xy:
            if self._in_bounds(x, y):
                new_blocked.add(self._to_idx(x, y))

        if new_blocked == self._dynamic_blocked:
            return False

        changed_nodes = self._dynamic_blocked.symmetric_difference(new_blocked)
        self._dynamic_blocked = new_blocked

        for idx in changed_nodes:
            self._recompute_rhs(idx)
            for pred in self._pred(idx):
                self._recompute_rhs(pred)

        if changed_nodes:
            self._compute_shortest_path()

        return True

    def step(self) -> Direction | None:
        if self._allow_jumps:
            raise RuntimeError(
                "step() is undefined when allow_jumps=True; use extract_path()"
            )
        if self._start == self._goal:
            return Direction.CENTRE

        self._compute_shortest_path()

        g = self._g
        start = self._start
        if g[start] == _INF:
            return None

        w = self._w
        h = self._h
        x = start % w
        y = start // w
        arr = self._env._array
        mask = self._block_mask
        dyn = self._dynamic_blocked

        best = None
        best_cost = _INF

        for dx, dy, cost, d in _NEIGHBOURS:
            xx = x + dx
            if xx < 0 or xx >= w:
                continue
            yy = y + dy
            if yy < 0 or yy >= h:
                continue
            s = yy * w + xx
            if s in dyn:
                continue
            if (mask >> arr[s]) & 1:
                continue
            v = cost + g[s]
            if v < best_cost:
                best_cost = v
                best = d

        return best

    def plan(self) -> None:
        self._compute_shortest_path()

    def extract_path_lines(self) -> list[tuple[float, float, float, float]]:
        """Return line segments [(x1,y1,x2,y2), ...] for rendering."""
        pts = self.extract_path()
        if len(pts) < 2:
            return []

        lines = []
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]

            # center of tiles
            lines.append((x1, y1, x2, y2))

        return lines

    def extract_path(self) -> list[tuple[int, int]]:
        """Return full path from current start to goal as (x,y). Empty if unreachable."""
        g = self._g
        start = self._start
        goal = self._goal
        if g[start] == _INF:
            return []

        w = self._w
        h = self._h
        arr = self._env._array
        mask = self._block_mask
        dyn = self._dynamic_blocked

        path: list[tuple[int, int]] = []
        cur = start

        visited = set()  # safety against rare inconsistency loops

        while cur != goal:
            x = cur % w
            y = cur // w
            path.append((x, y))
            visited.add(cur)

            best = None
            best_cost = _INF

            for dx, dy, cost, _ in _NEIGHBOURS:
                xx = x + dx
                if xx < 0 or xx >= w:
                    continue
                yy = y + dy
                if yy < 0 or yy >= h:
                    continue
                nxt = yy * w + xx
                if nxt in dyn:
                    continue
                if (mask >> arr[nxt]) & 1:
                    continue
                v = cost + g[nxt]
                if v < best_cost:
                    best_cost = v
                    best = nxt

            if best is None or best in visited:
                return []  # no valid path

            cur = best

        path.append((goal % w, goal // w))
        return path

    # ---------- Core D* Lite ----------

    def _compute_shortest_path(self) -> None:
        open_heap = self._open
        in_open = self._in_open
        g = self._g
        rhs = self._rhs
        w = self._w
        h = self._h
        recompute = self._recompute_rhs

        while open_heap:
            k_old, u = heapq.heappop(open_heap)

            if not in_open[u]:
                continue

            k_new = self._calc_key(u)
            if k_old < k_new:
                heapq.heappush(open_heap, (k_new, u))
                continue

            in_open[u] = False

            x = u % w
            y = u // w

            if g[u] > rhs[u]:
                g[u] = rhs[u]
                also_self = False
            else:
                g[u] = _INF
                also_self = True
            # Inlined: for p in _pred(u): _recompute_rhs(p)
            if y > 0:
                recompute(u - w)
                if x > 0:
                    recompute(u - w - 1)
                if x < w - 1:
                    recompute(u - w + 1)
            if y < h - 1:
                recompute(u + w)
                if x > 0:
                    recompute(u + w - 1)
                if x < w - 1:
                    recompute(u + w + 1)
            if x > 0:
                recompute(u - 1)
            if x < w - 1:
                recompute(u + 1)

            if also_self:
                recompute(u)

            if not open_heap:
                break

            start = self._start
            if (
                self._calc_key(start) <= open_heap[0][0]
                and rhs[start] == g[start]
            ):
                break

    def _recompute_rhs(self, u: int) -> None:
        if u == self._goal:
            return

        w = self._w
        h = self._h
        x = u % w
        y = u // w

        g = self._g
        arr = self._env._array
        mask = self._block_mask
        start = self._start
        dyn = self._dynamic_blocked
        unk_cost = self._unknown_cost

        min_rhs = _INF

        # Interior cells (the common case) skip all per-neighbour bounds
        # checks. Early-prune when g[s] >= min_rhs: since cost >= 1.0, we
        # cannot possibly beat min_rhs from such an s.
        if 0 < x < w - 1 and 0 < y < h - 1:
            s = u - w  # N
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + w  # S
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u - 1  # W
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + 1  # E
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u - w - 1  # NW
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u - w + 1  # NE
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + w - 1  # SW
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + w + 1  # SE
            if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                gs = g[s]
                if gs < min_rhs:
                    v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                    if v < min_rhs:
                        min_rhs = v
        else:
            # Border: per-direction bounds checks.
            if y > 0:
                s = u - w  # N
                if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v
                if x > 0:
                    s = u - w - 1  # NW
                    if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                        gs = g[s]
                        if gs < min_rhs:
                            v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                            if v < min_rhs:
                                min_rhs = v
                if x < w - 1:
                    s = u - w + 1  # NE
                    if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                        gs = g[s]
                        if gs < min_rhs:
                            v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                            if v < min_rhs:
                                min_rhs = v
            if y < h - 1:
                s = u + w  # S
                if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v
                if x > 0:
                    s = u + w - 1  # SW
                    if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                        gs = g[s]
                        if gs < min_rhs:
                            v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                            if v < min_rhs:
                                min_rhs = v
                if x < w - 1:
                    s = u + w + 1  # SE
                    if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                        gs = g[s]
                        if gs < min_rhs:
                            v = (_SQRT2 * unk_cost if arr[s] == 0 else _SQRT2) + gs
                            if v < min_rhs:
                                min_rhs = v
            if x > 0:
                s = u - 1  # W
                if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v
            if x < w - 1:
                s = u + 1  # E
                if s == start or (s not in dyn and not (mask >> arr[s]) & 1):
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v

        self._rhs[u] = min_rhs
        # Inlined _maybe_enqueue + _enqueue.
        if g[u] != min_rhs:
            gu = g[u]
            g_rhs = min_rhs if min_rhs < gu else gu
            dx = self._start_x - x
            if dx < 0:
                dx = -dx
            dy = self._start_y - y
            if dy < 0:
                dy = -dy
            m = dx if dx < dy else dy
            key = (g_rhs + (dx + dy) + (_SQRT2 - 2) * m + self._km, g_rhs)
            heapq.heappush(self._open, (key, u))
            self._in_open[u] = True

    def _enqueue(self, u: int) -> None:
        heapq.heappush(self._open, (self._calc_key(u), u))
        self._in_open[u] = True

    def _calc_key(self, u: int) -> tuple[float, float]:
        gu = self._g[u]
        ru = self._rhs[u]
        g_rhs = ru if ru < gu else gu

        w = self._w
        ux = u % w
        uy = u // w
        dx = self._start_x - ux
        if dx < 0:
            dx = -dx
        dy = self._start_y - uy
        if dy < 0:
            dy = -dy
        m = dx if dx < dy else dy
        h = (dx + dy) + (_SQRT2 - 2) * m

        return (g_rhs + h + self._km, g_rhs)

    # ---------- Helpers ----------

    def _heuristic(self, a: int, b: int) -> float:
        ax, ay = self._to_xy(a)
        bx, by = self._to_xy(b)
        dx = abs(ax - bx)
        dy = abs(ay - by)
        return (dx + dy) + (_SQRT2 - 2) * min(dx, dy)

    def _succ(self, u: int):
        x, y = self._to_xy(u)
        for dx, dy, cost, _ in _NEIGHBOURS:
            xx, yy = x + dx, y + dy
            if self._in_bounds(xx, yy):
                yield self._to_idx(xx, yy), cost

    def _pred(self, u: int):
        return (s for s, _ in self._succ(u))

    def _blocked(self, idx: int) -> bool:
        if idx == self._start:
            return False
        if idx in self._dynamic_blocked:
            return True
        return bool((self._block_mask >> self._env._array[idx]) & 1)

    def _to_idx(self, x: int, y: int) -> int:
        return y * self._w + x

    def _to_xy(self, idx: int) -> tuple[int, int]:
        return idx % self._w, idx // self._w

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._w and 0 <= y < self._h
