import heapq
import math
from typing import List, Tuple

from cambc import Controller, Direction, GameConstants

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

_DEFAULT_DEADLINE_US = 1800
_DEFAULT_EPSILON = 3.0
_DEFAULT_EPSILON_DECREMENT = 0.5
_EPSILON_MIN = 1.0


# Per-(w, h, use_bridges) precomputed adjacency. Map shape never changes after
# planner construction, so iteration tables are reusable across set_goal/init
# cycles inside a subinterpreter.
_STEP_TABLE_CACHE: dict[tuple[int, int, bool], tuple] = {}
_SUCC_TABLE_CACHE: dict[tuple[int, int, bool], tuple] = {}
_BRIDGE_TABLE_CACHE: dict[tuple[int, int], tuple] = {}


def _build_step_table(w: int, h: int, use_bridges: bool) -> tuple:
    """Per-cell tuple of (idx, cost, direction) for in-bounds 8-neighbours.
    Cost picks the bridge or non-bridge diagonal weight."""
    neighbours = _NEIGHBOURS_BRIDGE if use_bridges else _NEIGHBOURS
    out: list[tuple] = []
    for y in range(h):
        for x in range(w):
            entries = []
            for dx, dy, cost, direction in neighbours:
                xx = x + dx
                yy = y + dy
                if 0 <= xx < w and 0 <= yy < h:
                    entries.append((yy * w + xx, cost, direction))
            out.append(tuple(entries))
    return tuple(out)


def _build_succ_table(w: int, h: int, use_bridges: bool) -> tuple:
    """Per-cell tuple of (idx, cost) for the 8-neighbour walking edges. Used by
    _update_state and as the predecessor list (the grid is symmetric)."""
    neighbours = _NEIGHBOURS_BRIDGE if use_bridges else _NEIGHBOURS
    out: list[tuple] = []
    for y in range(h):
        for x in range(w):
            entries = []
            for dx, dy, cost, _ in neighbours:
                xx = x + dx
                yy = y + dy
                if 0 <= xx < w and 0 <= yy < h:
                    entries.append((yy * w + xx, cost))
            out.append(tuple(entries))
    return tuple(out)


def _build_bridge_table(w: int, h: int) -> tuple:
    """Per-cell tuple of in-bounds bridge-reachable indices. _BRIDGE_JUMPS is
    symmetric, so this serves as both successors and predecessors."""
    out: list[tuple] = []
    for y in range(h):
        for x in range(w):
            entries = []
            for jdx, jdy in _BRIDGE_JUMPS:
                jx = x + jdx
                jy = y + jdy
                if 0 <= jx < w and 0 <= jy < h:
                    entries.append(jy * w + jx)
            out.append(tuple(entries))
    return tuple(out)


def _get_step_table(w: int, h: int, use_bridges: bool) -> tuple:
    key = (w, h, use_bridges)
    t = _STEP_TABLE_CACHE.get(key)
    if t is None:
        t = _build_step_table(w, h, use_bridges)
        _STEP_TABLE_CACHE[key] = t
    return t


def _get_succ_table(w: int, h: int, use_bridges: bool) -> tuple:
    key = (w, h, use_bridges)
    t = _SUCC_TABLE_CACHE.get(key)
    if t is None:
        t = _build_succ_table(w, h, use_bridges)
        _SUCC_TABLE_CACHE[key] = t
    return t


def _get_bridge_table(w: int, h: int) -> tuple:
    key = (w, h)
    t = _BRIDGE_TABLE_CACHE.get(key)
    if t is None:
        t = _build_bridge_table(w, h)
        _BRIDGE_TABLE_CACHE[key] = t
    return t


class AnytimeDStar:
    """Anytime Dynamic A* (Likhachev et al.).

    Same API surface as DStarLite, plus a CPU-elapsed deadline (default 1800 us)
    that pauses ComputeOrImprovePath when c.get_cpu_time_elapsed() exceeds it.
    State (OPEN/CLOSED/INCONS, epsilon, g, rhs) persists across calls so the
    next invocation resumes the same iteration.

    Within a turn, work spans calls to plan/step/step_xy/notify_map_changes/
    set_dynamic_blockers; once cumulative CPU passes the deadline, all of them
    short-circuit until the runtime resets the counter on the next turn.
    """

    __slots__ = (
        "_c",
        "_env",
        "_w",
        "_h",
        "_n",
        "_g",
        "_rhs",
        "_open",
        "_in_open",
        "_closed",
        "_in_incons",
        "_incons",
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
        "_deadline_us",
        "_epsilon",
        "_epsilon_initial",
        "_epsilon_decrement",
        "_step_table",
        "_succ_table",
        "_bridge_table",
    )

    def __init__(
        self,
        c: Controller,
        env: EnvironmentMap,
        goal_x: int,
        goal_y: int,
        *,
        block_mask: int = _DEFAULT_BLOCK_MASK,
        unknown_cost: float = 1.0,
        use_bridges: bool = False,
        deadline_us: int = _DEFAULT_DEADLINE_US,
        epsilon_initial: float = _DEFAULT_EPSILON,
        epsilon_decrement: float = _DEFAULT_EPSILON_DECREMENT,
    ):
        self._c = c
        self._env = env
        w = env._w
        h = env._h
        self._w = w
        self._h = h
        self._n = w * h
        self._block_mask = block_mask
        self._deadline_us = deadline_us
        self._epsilon_initial = epsilon_initial
        self._epsilon_decrement = epsilon_decrement
        self._epsilon = epsilon_initial

        n = self._n
        self._g = [_INF] * n
        self._rhs = [_INF] * n

        self._open: List[Tuple[Tuple[float, float], int]] = []
        self._in_open = bytearray(n)
        self._closed = bytearray(n)
        self._in_incons = bytearray(n)
        self._incons: list[int] = []

        self._km = 0.0

        self._goal = goal_y * w + goal_x
        self._start = self._goal
        self._start_x = goal_x
        self._start_y = goal_y
        self._last = self._start

        self._rhs[self._goal] = 0.0

        self._snapshot = bytearray(env._array)
        self._dynamic_blocked: set[int] = set()

        # Combined static-mask + dynamic blocker bitmap with the invariant that
        # the current cell is always walkable.
        self._blocked = bytearray(n)
        for i, v in enumerate(env._array):
            if (block_mask >> v) & 1:
                self._blocked[i] = 1
        self._blocked[self._start] = 0

        self._unknown_cost = unknown_cost
        self._use_bridges = use_bridges
        self._diag_cost = _BRIDGE_JUMP_COST if use_bridges else _SQRT2

        self._step_table = _get_step_table(w, h, use_bridges)
        self._succ_table = _get_succ_table(w, h, use_bridges)
        # Always a tuple so subscripting is type-safe; the use_bridges guard
        # keeps non-bridge planners from ever building or touching it.
        self._bridge_table: tuple = (
            _get_bridge_table(w, h) if use_bridges else ()
        )

        self._enqueue(self._goal)

    # ---------- Public API ----------

    def set_goal(self, gx: int, gy: int) -> None:
        self.__init__(
            self._c,
            self._env,
            gx,
            gy,
            block_mask=self._block_mask,
            unknown_cost=self._unknown_cost,
            use_bridges=self._use_bridges,
            deadline_us=self._deadline_us,
            epsilon_initial=self._epsilon_initial,
            epsilon_decrement=self._epsilon_decrement,
        )

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

        # Edge costs changed: start a new AD* iteration at the current epsilon.
        self._begin_new_iteration()
        self._compute_or_improve_path()
        return True

    def set_dynamic_blockers(self, blocked_xy: list[tuple[int, int]]) -> bool:
        w = self._w
        h = self._h
        new_blocked = {y * w + x for x, y in blocked_xy if 0 <= x < w and 0 <= y < h}

        old_blocked = self._dynamic_blocked
        if new_blocked == old_blocked:
            return False

        # Sort the changed indices so refresh order is deterministic across runs
        # (set iteration order over ints is stable per-build but not specified).
        changed = sorted(old_blocked.symmetric_difference(new_blocked))
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

        self._begin_new_iteration()
        self._compute_or_improve_path()
        return True

    def step(self) -> Direction | None:
        start = self._start
        if start == self._goal:
            return Direction.CENTRE

        self._compute_or_improve_path()
        g = self._g
        if g[start] == _INF:
            return None

        blocked = self._blocked
        best = None
        best_cost = _INF
        for s, cost, d in self._step_table[start]:
            if blocked[s]:
                continue
            v = cost + g[s]
            if v < best_cost:
                best_cost = v
                best = d
        return best

    def step_xy(self) -> tuple[int, int] | None:
        """Like step(), but returns (x, y) of the next cell.
        With use_bridges=True the result may be at bridge-jump distance."""
        w = self._w
        start = self._start
        goal = self._goal
        if start == goal:
            return (goal % w, goal // w)

        self._compute_or_improve_path()
        g = self._g
        if g[start] == _INF:
            return None

        blocked = self._blocked
        best_idx: int | None = None
        best_cost = _INF
        for s, cost, _ in self._step_table[start]:
            if blocked[s]:
                continue
            v = cost + g[s]
            if v < best_cost:
                best_cost = v
                best_idx = s

        if self._use_bridges:
            for s in self._bridge_table[start]:
                if blocked[s]:
                    continue
                v = _BRIDGE_JUMP_COST + g[s]
                if v < best_cost:
                    best_cost = v
                    best_idx = s

        if best_idx is None:
            return None
        return (best_idx % w, best_idx // w)

    def plan(self) -> None:
        self._compute_or_improve_path()

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
        blocked = self._blocked
        step_table = self._step_table
        path: list[tuple[int, int]] = []
        cur = start
        visited: set[int] = set()  # safety against rare inconsistency loops

        while cur != goal:
            path.append((cur % w, cur // w))
            visited.add(cur)

            best = None
            best_cost = _INF
            for s, cost, _ in step_table[cur]:
                if blocked[s]:
                    continue
                v = cost + g[s]
                if v < best_cost:
                    best_cost = v
                    best = s

            if best is None or best in visited:
                return []
            cur = best

        path.append((goal % w, goal // w))
        return path

    # ---------- Core AD* ----------

    def _compute_or_improve_path(self) -> None:
        """Run ComputeOrImprovePath. When it finishes within budget and
        epsilon > 1, decrement epsilon and start a fresh sub-iteration so
        leftover budget tightens the suboptimality bound."""
        c = self._c
        deadline = self._deadline_us
        decrement = self._epsilon_decrement

        while True:
            if c.get_cpu_time_elapsed() > deadline:
                return

            self._process_iteration()

            if c.get_cpu_time_elapsed() > deadline:
                return

            # Goal unreachable from start — nothing more we can do.
            if self._g[self._start] != self._rhs[self._start]:
                return

            if self._epsilon <= _EPSILON_MIN:
                return

            new_eps = max(_EPSILON_MIN, self._epsilon - decrement)
            if new_eps == self._epsilon:
                return
            self._epsilon = new_eps
            self._begin_new_iteration()
            # If nothing's inconsistent, further sub-iterations would be no-ops.
            if not self._open:
                return

    def _process_iteration(self) -> None:
        """ComputeOrImprovePath body, paused when the CPU deadline trips.

        Hot loop: locals avoid attribute lookups; _calc_key is inlined for both
        the start-key termination check and the stale-key reinsertion test."""
        c = self._c
        get_cpu = c.get_cpu_time_elapsed
        deadline = self._deadline_us
        open_heap = self._open
        in_open = self._in_open
        g = self._g
        rhs = self._rhs
        w = self._w
        km = self._km
        eps = self._epsilon
        sx = self._start_x
        sy = self._start_y
        start = self._start
        closed = self._closed
        succ_table = self._succ_table
        use_bridges = self._use_bridges
        bridge_table = self._bridge_table
        update = self._update_state
        heappop = heapq.heappop
        heappush = heapq.heappush
        s2 = _SQRT2_MINUS_2
        inf = _INF

        while open_heap:
            if get_cpu() > deadline:
                return

            top_key = open_heap[0][0]

            # Inline _calc_key(start). h(start, start) == 0.
            g_start = g[start]
            rhs_start = rhs[start]
            if g_start > rhs_start:
                # Underconsistent starts shouldn't happen here, but the formula
                # collapses to (rhs+km, rhs) regardless when h==0.
                start_key = (rhs_start + km, rhs_start)
            else:
                start_key = (g_start + km, g_start)

            # Termination: top OPEN key >= key(start) AND start is consistent.
            if top_key >= start_key and rhs_start == g_start:
                return

            k_old, u = heappop(open_heap)
            if not in_open[u]:
                continue

            gu = g[u]
            ru = rhs[u]
            # Already consistent: drop the stale heap entry without touching g[u].
            if gu == ru:
                in_open[u] = 0
                continue

            # Inline _calc_key(u).
            dx = sx - u % w
            dy = sy - u // w
            if dx < 0:
                dx = -dx
            if dy < 0:
                dy = -dy
            h_u = (dx + dy) + s2 * (dx if dx < dy else dy)
            if gu > ru:
                k_new = (ru + eps * h_u + km, ru)
            else:
                k_new = (gu + h_u + km, gu)

            if k_old < k_new:
                heappush(open_heap, (k_new, u))
                continue

            in_open[u] = 0

            if gu > ru:
                # Overconsistent: lower g and propagate to predecessors.
                g[u] = ru
                closed[u] = 1
                for s, _ in succ_table[u]:
                    update(s)
                if use_bridges:
                    for s in bridge_table[u]:
                        update(s)
            else:
                # Underconsistent: raise g to inf and propagate (including self).
                g[u] = inf
                for s, _ in succ_table[u]:
                    update(s)
                update(u)
                if use_bridges:
                    for s in bridge_table[u]:
                        update(s)

    def _begin_new_iteration(self) -> None:
        """Move INCONS into OPEN, re-key everything with the current epsilon,
        and clear CLOSED. Called when edges change or epsilon decreases.

        Uses an insertion-order list dedup'd by a bytearray so the reseed order
        is deterministic across CPython builds (set iteration over ints is
        stable per-build only)."""
        n = self._n
        in_open = self._in_open
        in_incons = self._in_incons
        seen = bytearray(n)
        live: list[int] = []

        for _, u in self._open:
            if in_open[u] and not seen[u]:
                seen[u] = 1
                live.append(u)
        for u in self._incons:
            if in_incons[u] and not seen[u]:
                seen[u] = 1
                live.append(u)

        self._open = []
        self._in_open = bytearray(n)
        self._in_incons = bytearray(n)
        self._closed = bytearray(n)
        self._incons = []

        # Inline _enqueue across the batch: same key formula as _calc_key.
        g = self._g
        rhs = self._rhs
        open_heap = self._open
        new_in_open = self._in_open
        w = self._w
        sx = self._start_x
        sy = self._start_y
        eps = self._epsilon
        km = self._km
        s2 = _SQRT2_MINUS_2
        heappush = heapq.heappush

        for u in live:
            gu = g[u]
            ru = rhs[u]
            if gu == ru:
                continue
            dx = sx - u % w
            dy = sy - u // w
            if dx < 0:
                dx = -dx
            if dy < 0:
                dy = -dy
            h_u = (dx + dy) + s2 * (dx if dx < dy else dy)
            if gu > ru:
                key = (ru + eps * h_u + km, ru)
            else:
                key = (gu + h_u + km, gu)
            heappush(open_heap, (key, u))
            new_in_open[u] = 1

    def _update_state(self, u: int) -> None:
        """Recompute rhs(u) from successors and adjust OPEN/INCONS membership.

        Inlines walkable-neighbour iteration, bridge-neighbour iteration, and
        _enqueue's _calc_key to avoid generator+method overhead in the hottest
        loop of the planner."""
        g = self._g
        rhs = self._rhs

        if u != self._goal:
            arr = self._env._array
            blocked = self._blocked
            unk_cost = self._unknown_cost
            diag_cost = self._diag_cost
            use_bridges = self._use_bridges
            # In bridge mode unknown cells aren't penalised on diagonals: the
            # bridge cost dominates. Mirrors the original branch.
            diag_unk_cost = diag_cost if use_bridges else diag_cost * unk_cost

            min_rhs = _INF
            for s, cost in self._succ_table[u]:
                if blocked[s]:
                    continue
                if arr[s] == 0:
                    v = (diag_unk_cost if cost > 1.0 else unk_cost) + g[s]
                else:
                    v = cost + g[s]
                if v < min_rhs:
                    min_rhs = v

            if use_bridges:
                bjc = _BRIDGE_JUMP_COST
                for s in self._bridge_table[u]:
                    if blocked[s]:
                        continue
                    v = bjc + g[s]
                    if v < min_rhs:
                        min_rhs = v

            rhs[u] = min_rhs

        # Mark any live OPEN entry stale; new key (if needed) gets a fresh push.
        in_open = self._in_open
        if in_open[u]:
            in_open[u] = 0

        gu = g[u]
        ru = rhs[u]
        if gu != ru:
            if not self._closed[u]:
                # Inline _enqueue(u) — _calc_key uses current eps/km/start.
                w = self._w
                dx = self._start_x - u % w
                dy = self._start_y - u // w
                if dx < 0:
                    dx = -dx
                if dy < 0:
                    dy = -dy
                h_u = (dx + dy) + _SQRT2_MINUS_2 * (dx if dx < dy else dy)
                km = self._km
                if gu > ru:
                    key = (ru + self._epsilon * h_u + km, ru)
                else:
                    key = (gu + h_u + km, gu)
                heapq.heappush(self._open, (key, u))
                in_open[u] = 1
            else:
                in_incons = self._in_incons
                if not in_incons[u]:
                    in_incons[u] = 1
                    self._incons.append(u)

    def _refresh_neighbourhood(self, u: int) -> None:
        """Recompute u, its 8 neighbours, and (if enabled) bridge predecessors."""
        update = self._update_state
        update(u)
        for s, _ in self._succ_table[u]:
            update(s)
        if self._use_bridges:
            for s in self._bridge_table[u]:
                update(s)

    def _enqueue(self, u: int) -> None:
        """Out-of-band enqueue used during construction. Hot-path enqueues are
        inlined into _update_state and _begin_new_iteration."""
        gu = self._g[u]
        ru = self._rhs[u]
        w = self._w
        dx = self._start_x - u % w
        dy = self._start_y - u // w
        if dx < 0:
            dx = -dx
        if dy < 0:
            dy = -dy
        h_u = (dx + dy) + _SQRT2_MINUS_2 * (dx if dx < dy else dy)
        km = self._km
        if gu > ru:
            key = (ru + self._epsilon * h_u + km, ru)
        else:
            key = (gu + h_u + km, gu)
        heapq.heappush(self._open, (key, u))
        self._in_open[u] = 1

    # ---------- Helpers ----------

    def _heuristic(self, a: int, b: int) -> float:
        w = self._w
        ax = a % w
        ay = a // w
        bx = b % w
        by = b // w
        dx = ax - bx
        dy = ay - by
        if dx < 0:
            dx = -dx
        if dy < 0:
            dy = -dy
        return (dx + dy) + _SQRT2_MINUS_2 * (dx if dx < dy else dy)
