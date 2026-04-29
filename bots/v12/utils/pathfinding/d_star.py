import heapq
import math
from typing import List, Tuple

from cambc import Direction, GameConstants

from utils.map.raw_map_representation import EnvironmentMap

_BRIDGE_D = math.ceil(math.sqrt(GameConstants.BRIDGE_TARGET_RADIUS_SQ))
# Offsets reachable only by bridge: more than one step but within bridge range.
_BRIDGE_JUMPS: list[tuple[int, int]] = [
    (dx, dy)
    for dy in range(-_BRIDGE_D, _BRIDGE_D + 1)
    for dx in range(-_BRIDGE_D, _BRIDGE_D + 1)
    if 2 < dx * dx + dy * dy <= GameConstants.BRIDGE_TARGET_RADIUS_SQ
]
_BRIDGE_JUMP_COST = 5.0

_INF = float("inf")
_SQRT2 = math.sqrt(2)
_SQRT2_MINUS_2 = _SQRT2 - 2.0

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
# Like _RETURN_BLOCK_MASK but allows UNKNOWN tiles so the seek planner can
# route through unexplored space.
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
        "_start_x",
        "_start_y",
        "_goal",
        "_last",
        "_snapshot",
        "_block_mask",
        "_dynamic_blocked",
        "_blocked",
        "_unknown_cost",
        "_use_bridges",
        "_diag_cost",
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

        self._g = [_INF] * self._n
        self._rhs = [_INF] * self._n

        self._open: List[Tuple[Tuple[float, float], int]] = []
        self._in_open = [False] * self._n

        self._km = 0.0

        self._goal = goal_y * self._w + goal_x
        self._start = self._goal
        self._start_x = goal_x
        self._start_y = goal_y
        self._last = self._start

        self._rhs[self._goal] = 0.0
        self._enqueue(self._goal)

        self._snapshot = bytearray(env._array)
        self._dynamic_blocked: set[int] = set()

        # Combined static-mask + dynamic blocker bitmap with the invariant that
        # the current cell is always walkable.
        self._blocked = bytearray(self._n)
        for i, v in enumerate(env._array):
            if (block_mask >> v) & 1:
                self._blocked[i] = 1
        self._blocked[self._start] = 0

        self._unknown_cost = unknown_cost
        self._use_bridges = use_bridges
        self._diag_cost = _BRIDGE_JUMP_COST if use_bridges else _SQRT2

    # ---------- Public API ----------

    def set_goal(self, gx: int, gy: int) -> None:
        self.__init__(self._env, gx, gy, block_mask=self._block_mask)

    def set_position(self, sx: int, sy: int) -> None:
        new_start = sy * self._w + sx
        old_start = self._start
        if new_start == old_start:
            return

        self._km += self._heuristic(old_start, new_start)
        self._last = new_start
        self._start = new_start
        self._start_x = sx
        self._start_y = sy

        arr = self._env._array
        mask = self._block_mask
        dyn = self._dynamic_blocked

        # Restore old_start's true blocked state; force new_start walkable.
        old_truly_blocked = bool((mask >> arr[old_start]) & 1) or old_start in dyn
        if old_truly_blocked:
            self._blocked[old_start] = 1
            self._refresh_neighbourhood(old_start)

        if self._blocked[new_start]:
            self._blocked[new_start] = 0
            self._refresh_neighbourhood(new_start)

    def notify_map_changes(self) -> bool:
        arr = self._env._array
        snapshot = self._snapshot
        if arr == snapshot:
            return False

        blocked = self._blocked
        dyn = self._dynamic_blocked
        mask = self._block_mask
        start = self._start

        for i in range(self._n):
            if arr[i] == snapshot[i]:
                continue
            new_val = arr[i]
            snapshot[i] = new_val

            if i == start:
                blocked[i] = 0
            elif (mask >> new_val) & 1 or i in dyn:
                blocked[i] = 1
            else:
                blocked[i] = 0

            self._refresh_neighbourhood(i)

        self._compute_shortest_path()
        return True

    def set_dynamic_blockers(self, blocked_xy: list[tuple[int, int]]) -> bool:
        w = self._w
        h = self._h
        new_blocked = {y * w + x for x, y in blocked_xy if 0 <= x < w and 0 <= y < h}

        old_blocked = self._dynamic_blocked
        if new_blocked == old_blocked:
            return False

        changed = old_blocked.symmetric_difference(new_blocked)
        self._dynamic_blocked = new_blocked

        blocked = self._blocked
        arr = self._env._array
        mask = self._block_mask
        start = self._start

        for idx in changed:
            if idx == start:
                blocked[idx] = 0
            elif (mask >> arr[idx]) & 1 or idx in new_blocked:
                blocked[idx] = 1
            else:
                blocked[idx] = 0
            self._refresh_neighbourhood(idx)

        self._compute_shortest_path()
        return True

    def step(self) -> Direction | None:
        if self._start == self._goal:
            return Direction.CENTRE

        self._compute_shortest_path()
        g = self._g
        if g[self._start] == _INF:
            return None

        best = None
        best_cost = _INF
        for s, cost, d in self._walk_neighbours(self._start):
            v = cost + g[s]
            if v < best_cost:
                best_cost = v
                best = d
        return best

    def step_xy(self) -> tuple[int, int] | None:
        """Like step(), but returns (x, y) of the next cell.
        With use_bridges=True the result may be at bridge-jump distance."""
        w = self._w
        if self._start == self._goal:
            return (self._goal % w, self._goal // w)

        self._compute_shortest_path()
        g = self._g
        if g[self._start] == _INF:
            return None

        best_idx: int | None = None
        best_cost = _INF
        for s, cost, _ in self._walk_neighbours(self._start):
            v = cost + g[s]
            if v < best_cost:
                best_cost = v
                best_idx = s

        if self._use_bridges:
            for s in self._bridge_neighbours(self._start):
                v = _BRIDGE_JUMP_COST + g[s]
                if v < best_cost:
                    best_cost = v
                    best_idx = s

        if best_idx is None:
            return None
        return (best_idx % w, best_idx // w)

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
        g = self._g
        start = self._start
        goal = self._goal
        if g[start] == _INF:
            return []

        w = self._w
        path: list[tuple[int, int]] = []
        cur = start
        visited: set[int] = set()  # safety against rare inconsistency loops

        while cur != goal:
            path.append((cur % w, cur // w))
            visited.add(cur)

            best = None
            best_cost = _INF
            for s, cost, _ in self._walk_neighbours(cur):
                v = cost + g[s]
                if v < best_cost:
                    best_cost = v
                    best = s

            if best is None or best in visited:
                return []
            cur = best

        path.append((goal % w, goal // w))
        return path

    # ---------- Core D* Lite ----------

    def _compute_shortest_path(self) -> None:
        open_heap = self._open
        in_open = self._in_open
        g = self._g
        rhs = self._rhs
        start = self._start

        while open_heap:
            k_old, u = heapq.heappop(open_heap)
            if not in_open[u]:
                continue

            gu = g[u]
            ru = rhs[u]

            # Already consistent: drop the stale heap entry without touching g[u].
            if gu == ru:
                in_open[u] = False
                continue

            k_new = self._calc_key(u)
            if k_old < k_new:
                heapq.heappush(open_heap, (k_new, u))
                continue

            in_open[u] = False

            if gu > ru:
                g[u] = ru
                also_self = False
            else:
                g[u] = _INF
                also_self = True

            for p in self._predecessors(u):
                self._recompute_rhs(p)
            if also_self:
                self._recompute_rhs(u)
            if self._use_bridges:
                for p in self._bridge_predecessors(u):
                    self._recompute_rhs(p)

            if not open_heap:
                break

            # h(start, start) == 0, so calc_key(start) == (g[start]+km, g[start])
            # at the termination condition.
            gs = g[start]
            if rhs[start] == gs and (gs + self._km, gs) <= open_heap[0][0]:
                break

    def _recompute_rhs(self, u: int) -> None:
        if u == self._goal:
            return

        arr = self._env._array
        g = self._g
        unk_cost = self._unknown_cost
        diag_cost = self._diag_cost
        diag_unk_cost = diag_cost if self._use_bridges else diag_cost * unk_cost

        min_rhs = _INF
        for s, dx, dy in self._walkable_neighbours(u):
            is_diag = dx and dy
            if arr[s] == 0:
                cost = diag_unk_cost if is_diag else unk_cost
            else:
                cost = diag_cost if is_diag else 1.0
            v = cost + g[s]
            if v < min_rhs:
                min_rhs = v

        if self._use_bridges:
            for s in self._bridge_neighbours(u):
                v = _BRIDGE_JUMP_COST + g[s]
                if v < min_rhs:
                    min_rhs = v

        self._rhs[u] = min_rhs
        if g[u] != min_rhs:
            self._enqueue(u)
        else:
            # Consistent: invalidate any stale heap entry via lazy deletion.
            self._in_open[u] = False

    def _refresh_neighbourhood(self, u: int) -> None:
        """Recompute u, its 8 neighbours, and (if enabled) bridge predecessors."""
        self._recompute_rhs(u)
        for p in self._predecessors(u):
            self._recompute_rhs(p)
        if self._use_bridges:
            for p in self._bridge_predecessors(u):
                self._recompute_rhs(p)

    def _enqueue(self, u: int) -> None:
        heapq.heappush(self._open, (self._calc_key(u), u))
        self._in_open[u] = True

    def _calc_key(self, u: int) -> tuple[float, float]:
        gu = self._g[u]
        ru = self._rhs[u]
        g_rhs = ru if ru < gu else gu

        w = self._w
        dx = abs(self._start_x - u % w)
        dy = abs(self._start_y - u // w)
        h = (dx + dy) + _SQRT2_MINUS_2 * min(dx, dy)
        return (g_rhs + h + self._km, g_rhs)

    # ---------- Helpers ----------

    def _heuristic(self, a: int, b: int) -> float:
        w = self._w
        dx = abs(a % w - b % w)
        dy = abs(a // w - b // w)
        return (dx + dy) + _SQRT2_MINUS_2 * min(dx, dy)

    def _predecessors(self, u: int):
        """Yield in-bounds neighbour indices of u."""
        w = self._w
        h = self._h
        x = u % w
        y = u // w
        for dx, dy, _, _ in _NEIGHBOURS:
            xx = x + dx
            yy = y + dy
            if 0 <= xx < w and 0 <= yy < h:
                yield yy * w + xx

    def _walkable_neighbours(self, u: int):
        """Yield (idx, dx, dy) for in-bounds, unblocked neighbours of u."""
        w = self._w
        h = self._h
        blocked = self._blocked
        x = u % w
        y = u // w
        for dx, dy, _, _ in _NEIGHBOURS:
            xx = x + dx
            yy = y + dy
            if not (0 <= xx < w and 0 <= yy < h):
                continue
            s = yy * w + xx
            if blocked[s]:
                continue
            yield s, dx, dy

    def _walk_neighbours(self, u: int):
        """Yield (idx, cost, direction) for unblocked neighbours under the active
        cost table (bridge or non-bridge)."""
        w = self._w
        h = self._h
        blocked = self._blocked
        x = u % w
        y = u // w
        neighbours = _NEIGHBOURS_BRIDGE if self._use_bridges else _NEIGHBOURS
        for dx, dy, cost, d in neighbours:
            xx = x + dx
            yy = y + dy
            if not (0 <= xx < w and 0 <= yy < h):
                continue
            s = yy * w + xx
            if blocked[s]:
                continue
            yield s, cost, d

    def _bridge_neighbours(self, u: int):
        """Yield in-bounds, unblocked bridge-reachable cells from u."""
        w = self._w
        h = self._h
        blocked = self._blocked
        x = u % w
        y = u // w
        for jdx, jdy in _BRIDGE_JUMPS:
            jx = x + jdx
            jy = y + jdy
            if not (0 <= jx < w and 0 <= jy < h):
                continue
            s = jy * w + jx
            if blocked[s]:
                continue
            yield s

    def _bridge_predecessors(self, u: int):
        """Yield in-bounds cells from which u is reachable via a bridge jump."""
        w = self._w
        h = self._h
        x = u % w
        y = u // w
        for jdx, jdy in _BRIDGE_JUMPS:
            px = x - jdx
            py = y - jdy
            if 0 <= px < w and 0 <= py < h:
                yield py * w + px
