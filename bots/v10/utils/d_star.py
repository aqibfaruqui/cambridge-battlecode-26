import heapq
import math
from typing import List, Tuple

from cambc import Direction

from utils.raw_map_representation import EnvironmentMap

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
# Like _RETURN_BLOCK_MASK but allows UNKNOWN and ORE_AXIONITE tiles — lets
# the seek planner route through unexplored space and axionite deposits.
_SEEK_BLOCK_MASK = (
    (1 << _WALL)
    | (1 << _ORE_TITANIUM)
    | (1 << _ENEMY_CORE)
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
        "_goal",
        "_last",
        "_snapshot",
        "_block_mask",
        "_dynamic_blocked",
    )

    def __init__(
        self,
        env: EnvironmentMap,
        goal_x: int,
        goal_y: int,
        *,
        block_mask: int = _DEFAULT_BLOCK_MASK,
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
        self._last = self._start

        self._rhs[self._goal] = 0.0
        self._enqueue(self._goal)

        self._snapshot = bytearray(env._array)
        self._dynamic_blocked: set[int] = set()

    # ---------- Public API ----------

    def set_goal(self, gx: int, gy: int) -> None:
        self.__init__(self._env, gx, gy, block_mask=self._block_mask)

    def set_position(self, sx: int, sy: int) -> None:
        new_start = self._to_idx(sx, sy)
        self._km += self._heuristic(self._last, new_start)
        self._last = new_start
        self._start = new_start

    def notify_map_changes(self) -> bool:
        changed = False
        arr = self._env._array

        for i in range(self._n):
            if arr[i] != self._snapshot[i]:
                changed = True
                self._snapshot[i] = arr[i]

                for pred in self._pred(i):
                    self._recompute_rhs(pred)

                self._recompute_rhs(i)

        if changed:
            self._compute_shortest_path()

        return changed

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
        if self._start == self._goal:
            return Direction.CENTRE

        self._compute_shortest_path()

        if self._g[self._start] == _INF:
            return None

        best = None
        best_cost = _INF

        for nx, ny, cost, d in _NEIGHBOURS:
            x, y = self._to_xy(self._start)
            xx, yy = x + nx, y + ny
            if not self._in_bounds(xx, yy):
                continue

            s = self._to_idx(xx, yy)
            if self._blocked(s):
                continue

            v = cost + self._g[s]
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
        if self._g[self._start] == _INF:
            return []

        path: list[tuple[int, int]] = []
        cur = self._start

        visited = set()  # safety against rare inconsistency loops

        while cur != self._goal:
            path.append(self._to_xy(cur))
            visited.add(cur)

            best = None
            best_cost = _INF

            x, y = self._to_xy(cur)

            for dx, dy, cost, _ in _NEIGHBOURS:
                xx, yy = x + dx, y + dy
                if not self._in_bounds(xx, yy):
                    continue

                nxt = self._to_idx(xx, yy)
                if self._blocked(nxt):
                    continue

                v = cost + self._g[nxt]
                if v < best_cost:
                    best_cost = v
                    best = nxt

            if best is None or best in visited:
                return []  # no valid path

            cur = best

        path.append(self._to_xy(self._goal))
        return path

    # ---------- Core D* Lite ----------

    def _compute_shortest_path(self) -> None:
        while self._open:
            k_old, u = heapq.heappop(self._open)

            if not self._in_open[u]:
                continue

            k_new = self._calc_key(u)
            if k_old < k_new:
                heapq.heappush(self._open, (k_new, u))
                continue

            self._in_open[u] = False

            if self._g[u] > self._rhs[u]:
                self._g[u] = self._rhs[u]
                for p in self._pred(u):
                    self._recompute_rhs(p)
            else:
                self._g[u] = _INF
                for p in self._pred(u):
                    self._recompute_rhs(p)
                self._recompute_rhs(u)

            if not self._open:
                break

            if (
                self._calc_key(self._start) <= self._open[0][0]
                and self._rhs[self._start] == self._g[self._start]
            ):
                break

    def _recompute_rhs(self, u: int) -> None:
        if u == self._goal:
            return

        min_rhs = _INF
        for s, cost in self._succ(u):
            if self._blocked(s):
                continue
            v = cost + self._g[s]
            if v < min_rhs:
                min_rhs = v

        self._rhs[u] = min_rhs
        self._maybe_enqueue(u)

    def _maybe_enqueue(self, u: int) -> None:
        if self._g[u] != self._rhs[u]:
            self._enqueue(u)

    def _enqueue(self, u: int) -> None:
        heapq.heappush(self._open, (self._calc_key(u), u))
        self._in_open[u] = True

    def _calc_key(self, u: int) -> tuple[float, float]:
        g_rhs = min(self._g[u], self._rhs[u])
        return (
            g_rhs + self._heuristic(self._start, u) + self._km,
            g_rhs,
        )

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
        return (self._block_mask >> self._env._array[idx]) & 1

    def _to_idx(self, x: int, y: int) -> int:
        return y * self._w + x

    def _to_xy(self, idx: int) -> tuple[int, int]:
        return idx % self._w, idx // self._w

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._w and 0 <= y < self._h
