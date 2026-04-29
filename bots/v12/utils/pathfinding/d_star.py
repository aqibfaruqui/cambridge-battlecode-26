import heapq
import math
from typing import List, Tuple

from cambc import Direction, GameConstants

from utils.map.raw_map_representation import EnvironmentMap

_BRIDGE_D = math.ceil(math.sqrt(GameConstants.BRIDGE_TARGET_RADIUS_SQ))
# All offsets that require a bridge (more than one step but within bridge range).
# Excludes the 8 adjacent neighbours (dist_sq <= 2) handled by normal moves.
_BRIDGE_JUMPS: list[tuple[int, int]] = [
    (dx, dy)
    for dy in range(-_BRIDGE_D, _BRIDGE_D + 1)
    for dx in range(-_BRIDGE_D, _BRIDGE_D + 1)
    if 2 < dx * dx + dy * dy <= GameConstants.BRIDGE_TARGET_RADIUS_SQ
]
_BRIDGE_JUMP_COST = 5.0

_INF = float("inf")
_SQRT2 = math.sqrt(2)
_OCTILE_DIAG_COEFF = _SQRT2 - 2.0  # h(a,b) = (dx+dy) + (sqrt2-2)*min(dx,dy)

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
_NEIGHBOURS_BRIDGE = (
    (0, -1, 1.0, Direction.NORTH),
    (1, -1, _BRIDGE_JUMP_COST, Direction.NORTHEAST),
    (1, 0, 1.0, Direction.EAST),
    (1, 1, _BRIDGE_JUMP_COST, Direction.SOUTHEAST),
    (0, 1, 1.0, Direction.SOUTH),
    (-1, 1, _BRIDGE_JUMP_COST, Direction.SOUTHWEST),
    (-1, 0, 1.0, Direction.WEST),
    (-1, -1, _BRIDGE_JUMP_COST, Direction.NORTHWEST),
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
_BRIDGE_WALK_BLOCK_MASK = (
    (1 << _WALL)
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
        "_unknown_cost",
        "_use_bridges",
    )

    def __init__(
        self,
        env: EnvironmentMap,
        goal_x: int,
        goal_y: int,
        *,
        block_mask: int = _DEFAULT_BLOCK_MASK,
        unknown_cost: float = 1.0,
        use_bridges: bool = False,
    ):
        self._env = env
        self._w = env._w
        self._h = env._h
        self._n = self._w * self._h
        self._block_mask = block_mask
        self._unknown_cost = unknown_cost
        self._use_bridges = use_bridges

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
        self.__init__(
            self._env,
            gx,
            gy,
            block_mask=self._block_mask,
            unknown_cost=self._unknown_cost,
            use_bridges=self._use_bridges,
        )

    def set_position(self, sx: int, sy: int) -> None:
        new_start = self._to_idx(sx, sy)
        old_start = self._start
        if new_start == old_start:
            return

        self._km += self._heuristic(self._last, new_start)
        self._last = new_start
        self._start = new_start

        # _is_blocked treats the current start as walkable. When that label
        # moves, neighbours of the cell that just lost (or just gained) the
        # override may need to recompute rhs.
        if self._has_blocking_state(old_start):
            self._propagate_at(old_start)
        if self._has_blocking_state(new_start):
            self._propagate_at(new_start)

    def notify_map_changes(self) -> bool:
        arr = self._env._array
        snapshot = self._snapshot

        # Fast path: bytearray equality is a single C memcmp.
        if arr == snapshot:
            return False

        for i in range(self._n):
            if arr[i] != snapshot[i]:
                snapshot[i] = arr[i]
                self._propagate_at(i)

        self._compute_shortest_path()
        return True

    def set_dynamic_blockers(self, blocked_xy: list[tuple[int, int]]) -> bool:
        w = self._w
        h = self._h
        new_blocked: set[int] = {
            y * w + x for x, y in blocked_xy if 0 <= x < w and 0 <= y < h
        }

        if new_blocked == self._dynamic_blocked:
            return False

        changed = self._dynamic_blocked.symmetric_difference(new_blocked)
        self._dynamic_blocked = new_blocked

        for idx in changed:
            self._recompute_rhs(idx)
            for p in self._pred(idx):
                self._recompute_rhs(p)

        if changed:
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
        for s, cost, d in self._step_candidates(self._start):
            v = cost + self._g[s]
            if v < best_cost:
                best_cost = v
                best = d
        return best

    def step_xy(self) -> tuple[int, int] | None:
        """Like step(), but returns (x, y) of the next cell.
        When use_bridges=True this can return a cell at bridge-jump distance."""
        if self._start == self._goal:
            return self._to_xy(self._goal)

        self._compute_shortest_path()
        if self._g[self._start] == _INF:
            return None

        best_idx: int | None = None
        best_cost = _INF
        for s, cost, _ in self._step_candidates(self._start):
            v = cost + self._g[s]
            if v < best_cost:
                best_cost = v
                best_idx = s

        if self._use_bridges:
            for s in self._bridge_succ(self._start):
                v = _BRIDGE_JUMP_COST + self._g[s]
                if v < best_cost:
                    best_cost = v
                    best_idx = s

        if best_idx is None:
            return None
        return self._to_xy(best_idx)

    def plan(self) -> None:
        self._compute_shortest_path()

    def extract_path_lines(self) -> list[tuple[int, int, int, int]]:
        """Return line segments [(x1,y1,x2,y2), ...] for rendering."""
        pts = self.extract_path()
        return [
            (pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
            for i in range(len(pts) - 1)
        ]

    def extract_path(self) -> list[tuple[int, int]]:
        """Return full path from current start to goal as (x,y). Empty if unreachable."""
        if self._g[self._start] == _INF:
            return []

        path: list[tuple[int, int]] = []
        visited: set[int] = set()  # safety against rare inconsistency loops
        cur = self._start

        while cur != self._goal:
            path.append(self._to_xy(cur))
            visited.add(cur)

            best = None
            best_cost = _INF
            for nxt, cost, _ in self._step_candidates(cur, use_bridges=False):
                v = cost + self._g[nxt]
                if v < best_cost:
                    best_cost = v
                    best = nxt

            if best is None or best in visited:
                return []
            cur = best

        path.append(self._to_xy(self._goal))
        return path

    # ---------- Core D* Lite ----------

    def _compute_shortest_path(self) -> None:
        open_heap = self._open
        in_open = self._in_open
        g = self._g
        rhs = self._rhs

        while open_heap:
            k_old, u = heapq.heappop(open_heap)
            if not in_open[u]:
                continue

            # Consistent stale entry: drop without touching g[u]. The canonical
            # else-branch below would overwrite a consistent g[u] with INF and
            # cascade spurious updates.
            if g[u] == rhs[u]:
                in_open[u] = False
                continue

            k_new = self._calc_key(u)
            if k_old < k_new:
                heapq.heappush(open_heap, (k_new, u))
                continue

            in_open[u] = False

            if g[u] > rhs[u]:
                g[u] = rhs[u]
                also_self = False
            else:
                g[u] = _INF
                also_self = True

            for p in self._pred(u):
                self._recompute_rhs(p)
            if also_self:
                self._recompute_rhs(u)
            if self._use_bridges:
                for p in self._bridge_pred(u):
                    self._recompute_rhs(p)

            if not open_heap:
                break

            # h(start, start) = 0, so calc_key(start) simplifies to (gs+km, gs)
            # whenever rhs[start] == g[start] (the termination condition).
            start = self._start
            gs = g[start]
            if rhs[start] == gs and (gs + self._km, gs) <= open_heap[0][0]:
                break

    def _recompute_rhs(self, u: int) -> None:
        if u == self._goal:
            return

        g = self._g
        min_rhs = _INF

        for s, cost, _ in self._step_candidates(u):
            v = cost + g[s]
            if v < min_rhs:
                min_rhs = v

        if self._use_bridges:
            for s in self._bridge_succ(u):
                v = _BRIDGE_JUMP_COST + g[s]
                if v < min_rhs:
                    min_rhs = v

        self._rhs[u] = min_rhs
        self._maybe_enqueue(u)

    def _maybe_enqueue(self, u: int) -> None:
        if self._g[u] != self._rhs[u]:
            self._enqueue(u)
        else:
            # Consistent: invalidate any stale open-heap entry. The entry
            # remains in the heap (lazy deletion); in_open[u]=False makes it
            # skip on pop, avoiding redundant processing.
            self._in_open[u] = False

    def _enqueue(self, u: int) -> None:
        heapq.heappush(self._open, (self._calc_key(u), u))
        self._in_open[u] = True

    def _calc_key(self, u: int) -> tuple[float, float]:
        gu = self._g[u]
        ru = self._rhs[u]
        g_rhs = ru if ru < gu else gu
        return (g_rhs + self._heuristic(u, self._start) + self._km, g_rhs)

    # ---------- Neighbour helpers ----------

    def _step_candidates(self, u: int, *, use_bridges: bool | None = None):
        """Yield (successor_idx, step_cost, direction) for the 8 adjacent
        neighbours of u that aren't blocked. Cost reflects use_bridges and
        the unknown-cell multiplier."""
        if use_bridges is None:
            use_bridges = self._use_bridges
        x, y = self._to_xy(u)
        arr = self._env._array
        unk = self._unknown_cost
        neighbours = _NEIGHBOURS_BRIDGE if use_bridges else _NEIGHBOURS

        for dx, dy, cost, d in neighbours:
            xx, yy = x + dx, y + dy
            if not self._in_bounds(xx, yy):
                continue
            s = self._to_idx(xx, yy)
            if self._is_blocked(s):
                continue
            # Unknown cells get the unk_cost multiplier — but only outside
            # bridge mode, where step costs are fixed.
            if not use_bridges and arr[s] == 0:
                yield s, cost * unk, d
            else:
                yield s, cost, d

    def _bridge_succ(self, u: int):
        """Yield successor indices reachable from u via a bridge jump."""
        x, y = self._to_xy(u)
        for jdx, jdy in _BRIDGE_JUMPS:
            jx, jy = x + jdx, y + jdy
            if self._in_bounds(jx, jy):
                s = self._to_idx(jx, jy)
                if not self._is_blocked(s):
                    yield s

    def _bridge_pred(self, u: int):
        """Yield predecessor indices that can bridge-jump into u."""
        x, y = self._to_xy(u)
        for jdx, jdy in _BRIDGE_JUMPS:
            px, py = x - jdx, y - jdy
            if self._in_bounds(px, py):
                yield self._to_idx(px, py)

    def _propagate_at(self, idx: int) -> None:
        """Recompute rhs for idx and every predecessor that depends on it."""
        self._recompute_rhs(idx)
        for p in self._pred(idx):
            self._recompute_rhs(p)
        if self._use_bridges:
            for p in self._bridge_pred(idx):
                self._recompute_rhs(p)

    def _succ(self, u: int):
        x, y = self._to_xy(u)
        for dx, dy, cost, _ in _NEIGHBOURS:
            xx, yy = x + dx, y + dy
            if self._in_bounds(xx, yy):
                yield self._to_idx(xx, yy), cost

    def _pred(self, u: int):
        return (s for s, _ in self._succ(u))

    # ---------- Blocked-state helpers ----------

    def _is_blocked(self, idx: int) -> bool:
        """The current start is always walkable, even if it sits on an ore
        tile or a dynamic blocker — the bot has to be able to move from
        wherever it stands."""
        if idx == self._start:
            return False
        if (self._block_mask >> self._env._array[idx]) & 1:
            return True
        return idx in self._dynamic_blocked

    def _has_blocking_state(self, idx: int) -> bool:
        """True if idx would be blocked ignoring the start-is-walkable override."""
        if (self._block_mask >> self._env._array[idx]) & 1:
            return True
        return idx in self._dynamic_blocked

    # ---------- Geometry helpers ----------

    def _heuristic(self, a: int, b: int) -> float:
        ax, ay = self._to_xy(a)
        bx, by = self._to_xy(b)
        dx = abs(ax - bx)
        dy = abs(ay - by)
        return (dx + dy) + _OCTILE_DIAG_COEFF * min(dx, dy)

    def _to_idx(self, x: int, y: int) -> int:
        return y * self._w + x

    def _to_xy(self, idx: int) -> tuple[int, int]:
        return idx % self._w, idx // self._w

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._w and 0 <= y < self._h
