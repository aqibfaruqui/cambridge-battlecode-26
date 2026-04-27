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
_SQRT2_MINUS_2 = _SQRT2 - 2.0  # octile heuristic coefficient; hoisted so hot paths skip the subtraction.

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
        "_recompute_rhs",
        "_bridge_offsets",
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
        # bytearray indexed by node id; 0 = stale/absent, 1 = live entry.
        # Faster than list[bool] for indexed writes (no Py_True/Py_False
        # rebind) and for the hot stale-entry check in _compute_shortest_path.
        self._in_open = bytearray(self._n)

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
        # Combined static-mask + dynamic blocker bitmap. Hot-path membership test
        # collapses (s not in dyn) and ((mask >> arr[s]) & 1) into one C-level
        # bytearray index. The invariant blocked[start]=0 is enforced across
        # set_position / notify_map_changes / set_dynamic_blockers so the
        # frequent `s == start` override in _recompute_rhs can be dropped.
        # Build the bitmap with a single C-level translate over the env array,
        # one byte per terrain code (0..255 covers the 7 enum values).
        mask = self._block_mask
        _table = bytes(((mask >> v) & 1) for v in range(256))
        self._blocked = bytearray(env._array).translate(_table)
        self._blocked[self._start] = 0  # force-walkable invariant for current position
        self._unknown_cost = unknown_cost
        self._use_bridges = use_bridges
        self._diag_cost = _BRIDGE_JUMP_COST if use_bridges else _SQRT2
        # Precompute flat per-row index offsets for bridge jumps, so the
        # interior fast path can iterate without per-iteration bounds checks.
        # `_BRIDGE_JUMPS` is geometric and depends only on the game constant.
        if use_bridges:
            w = self._w
            self._bridge_offsets = tuple(jdy * w + jdx for jdx, jdy in _BRIDGE_JUMPS)
        else:
            self._bridge_offsets = ()

        # Specialise the recompute hot path. The common case (unknown_cost==1.0
        # without bridges, which holds for every planner except the return one)
        # makes the per-neighbour `arr[s]==0` cost branch dead AND the bridge
        # loop dead, so we bind a uniform variant with literal step costs and
        # no bridge code. Anything else (return planner today, future hybrids)
        # falls back to the general implementation.
        if unknown_cost == 1.0 and not use_bridges:
            self._recompute_rhs = self._recompute_rhs_uniform  # type: ignore[method-assign]
        else:
            self._recompute_rhs = self._recompute_rhs_general  # type: ignore[method-assign]

    # ---------- Public API ----------

    def set_goal(self, gx: int, gy: int) -> None:
        self.__init__(self._env, gx, gy, block_mask=self._block_mask)

    def set_position(self, sx: int, sy: int) -> None:
        w = self._w
        new_start = sy * w + sx
        old_start = self._start
        if new_start == old_start:
            return

        # Heuristic(_last, new_start) inlined using cached coords.
        dx = self._start_x - sx
        if dx < 0:
            dx = -dx
        dy = self._start_y - sy
        if dy < 0:
            dy = -dy
        self._km += (dx + dy) + _SQRT2_MINUS_2 * (dx if dx < dy else dy)
        self._last = new_start
        self._start = new_start
        self._start_x = sx
        self._start_y = sy

        # Maintain the blocked[start]=0 invariant. For the common case where
        # both cells are walkable (bot just moved one square), nothing
        # propagates. Only when the bot stands on a blocked tile (e.g. just
        # placed a harvester on ore) do we trigger predecessor recomputes.
        arr = self._env._array
        mask = self._block_mask
        blocked = self._blocked
        dyn = self._dynamic_blocked
        h = self._h

        # Re-derive old_start's true blocked state (it was forced to 0).
        true_old = 1 if ((mask >> arr[old_start]) & 1) or (old_start in dyn) else 0
        if true_old != 0:
            blocked[old_start] = 1
            x = old_start % w
            y = old_start // w
            recompute = self._recompute_rhs
            recompute(old_start)
            if y > 0:
                recompute(old_start - w)
                if x > 0:
                    recompute(old_start - w - 1)
                if x < w - 1:
                    recompute(old_start - w + 1)
            if y < h - 1:
                recompute(old_start + w)
                if x > 0:
                    recompute(old_start + w - 1)
                if x < w - 1:
                    recompute(old_start + w + 1)
            if x > 0:
                recompute(old_start - 1)
            if x < w - 1:
                recompute(old_start + 1)

        # Force new_start unblocked. If it was blocked, propagate.
        if blocked[new_start]:
            blocked[new_start] = 0
            x = sx
            y = sy
            recompute = self._recompute_rhs
            recompute(new_start)
            if y > 0:
                recompute(new_start - w)
                if x > 0:
                    recompute(new_start - w - 1)
                if x < w - 1:
                    recompute(new_start - w + 1)
            if y < h - 1:
                recompute(new_start + w)
                if x > 0:
                    recompute(new_start + w - 1)
                if x < w - 1:
                    recompute(new_start + w + 1)
            if x > 0:
                recompute(new_start - 1)
            if x < w - 1:
                recompute(new_start + 1)

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
        blocked = self._blocked
        dyn = self._dynamic_blocked
        mask = self._block_mask
        use_bridges = self._use_bridges
        current_start = self._start

        i = 0
        while i < n:
            if arr[i] != snapshot[i]:
                new_val = arr[i]
                snapshot[i] = new_val

                # Refresh combined blocked bitmap for this cell. Preserve the
                # blocked[start]=0 invariant.
                if i == current_start:
                    blocked[i] = 0
                elif (mask >> new_val) & 1 or i in dyn:
                    blocked[i] = 1
                else:
                    blocked[i] = 0

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

                if use_bridges:
                    bd = _BRIDGE_D
                    if bd <= x < w - bd and bd <= y < h - bd:
                        for off in self._bridge_offsets:
                            recompute(i - off)
                    else:
                        for jdx, jdy in _BRIDGE_JUMPS:
                            px = x - jdx
                            py = y - jdy
                            if 0 <= px < w and 0 <= py < h:
                                recompute(py * w + px)

            i += 1

        self._compute_shortest_path()
        return True

    def set_dynamic_blockers(self, blocked_xy: list[tuple[int, int]]) -> bool:
        w = self._w
        h = self._h
        new_blocked: set[int] = set()
        for x, y in blocked_xy:
            if 0 <= x < w and 0 <= y < h:
                new_blocked.add(y * w + x)

        old_blocked = self._dynamic_blocked
        if new_blocked == old_blocked:
            return False

        changed_nodes = old_blocked.symmetric_difference(new_blocked)
        self._dynamic_blocked = new_blocked

        # Refresh combined bitmap + propagate rhs recomputes. Inline _pred —
        # the generator shows up as measurable overhead at 1400+ calls/turn.
        blocked = self._blocked
        arr = self._env._array
        mask = self._block_mask
        recompute = self._recompute_rhs
        current_start = self._start

        for idx in changed_nodes:
            if idx == current_start:
                blocked[idx] = 0  # preserve start=walkable invariant
            elif (mask >> arr[idx]) & 1:
                blocked[idx] = 1  # still statically blocked
            elif idx in new_blocked:
                blocked[idx] = 1
            else:
                blocked[idx] = 0

            x = idx % w
            y = idx // w
            recompute(idx)
            if y > 0:
                recompute(idx - w)
                if x > 0:
                    recompute(idx - w - 1)
                if x < w - 1:
                    recompute(idx - w + 1)
            if y < h - 1:
                recompute(idx + w)
                if x > 0:
                    recompute(idx + w - 1)
                if x < w - 1:
                    recompute(idx + w + 1)
            if x > 0:
                recompute(idx - 1)
            if x < w - 1:
                recompute(idx + 1)

        if changed_nodes:
            self._compute_shortest_path()

        return True

    def step(self) -> Direction | None:
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
        blocked = self._blocked

        best = None
        best_cost = _INF
        neighbours = _NEIGHBOURS_BRIDGE if self._use_bridges else _NEIGHBOURS

        for dx, dy, cost, d in neighbours:
            xx = x + dx
            if xx < 0 or xx >= w:
                continue
            yy = y + dy
            if yy < 0 or yy >= h:
                continue
            s = yy * w + xx
            if blocked[s]:
                continue
            v = cost + g[s]
            if v < best_cost:
                best_cost = v
                best = d

        return best

    def step_xy(self) -> tuple[int, int] | None:
        """Like step(), but returns (x, y) of the next cell.
        When use_bridges=True this can return a cell at bridge-jump distance."""
        if self._start == self._goal:
            return (self._goal % self._w, self._goal // self._w)

        self._compute_shortest_path()

        g = self._g
        start = self._start
        if g[start] == _INF:
            return None

        w = self._w
        h = self._h
        x = start % w
        y = start // w
        blocked = self._blocked

        best_idx: int | None = None
        best_cost = _INF
        neighbours = _NEIGHBOURS_BRIDGE if self._use_bridges else _NEIGHBOURS

        for dx, dy, cost, _ in neighbours:
            xx = x + dx
            if xx < 0 or xx >= w:
                continue
            yy = y + dy
            if yy < 0 or yy >= h:
                continue
            s = yy * w + xx
            if blocked[s]:
                continue
            v = cost + g[s]
            if v < best_cost:
                best_cost = v
                best_idx = s

        if self._use_bridges:
            for jdx, jdy in _BRIDGE_JUMPS:
                jx = x + jdx
                jy = y + jdy
                if 0 <= jx < w and 0 <= jy < h:
                    s = jy * w + jx
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
        self._compute_shortest_path()

    def extract_path_lines(self) -> list[tuple[int, int, int, int]]:
        """Return line segments [(x1,y1,x2,y2), ...] for rendering."""
        pts = self.extract_path()
        if len(pts) < 2:
            return []

        lines = []
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
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
        blocked = self._blocked

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
                if blocked[nxt]:
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
        h_minus_1 = self._h - 1
        w_minus_1 = w - 1
        recompute = self._recompute_rhs
        use_bridges = self._use_bridges

        # Start doesn't move inside this loop; cache once. km is also constant.
        start = self._start
        start_x = self._start_x
        start_y = self._start_y
        km = self._km

        while open_heap:
            k_old, u = heapq.heappop(open_heap)

            if not in_open[u]:
                continue

            gu = g[u]
            ru = rhs[u]

            # Consistent stale entry: skip without polluting g[u]. Without this
            # the canonical else-branch below set g[u]=INF for a consistent u,
            # cascading spurious updates before the next recompute corrected it.
            if gu == ru:
                in_open[u] = 0
                continue

            # Inlined calc_key(u) — this is the hottest call site.
            g_rhs = ru if ru < gu else gu
            ux = u % w
            uy = u // w
            dx = start_x - ux
            if dx < 0:
                dx = -dx
            dy = start_y - uy
            if dy < 0:
                dy = -dy
            m = dx if dx < dy else dy
            k_new_primary = g_rhs + (dx + dy) + _SQRT2_MINUS_2 * m + km
            # Avoid building the (k_new_primary, g_rhs) tuple just for the
            # compare — k_old is already a tuple, so unpack-and-compare in
            # scalar space (saves an allocation per heap pop, ~62k/run).
            k_old_0 = k_old[0]
            if k_old_0 < k_new_primary or (k_old_0 == k_new_primary and k_old[1] < g_rhs):
                heapq.heappush(open_heap, ((k_new_primary, g_rhs), u))
                continue

            in_open[u] = 0

            if gu > ru:
                g[u] = ru
                also_self = False
            else:
                g[u] = _INF
                also_self = True
            # Inlined: for p in _pred(u): _recompute_rhs(p)
            if uy > 0:
                recompute(u - w)
                if ux > 0:
                    recompute(u - w - 1)
                if ux < w_minus_1:
                    recompute(u - w + 1)
            if uy < h_minus_1:
                recompute(u + w)
                if ux > 0:
                    recompute(u + w - 1)
                if ux < w_minus_1:
                    recompute(u + w + 1)
            if ux > 0:
                recompute(u - 1)
            if ux < w_minus_1:
                recompute(u + 1)

            if also_self:
                recompute(u)

            if use_bridges:
                bd = _BRIDGE_D
                if bd <= ux <= w_minus_1 - bd and bd <= uy <= h_minus_1 - bd:
                    # All predecessor offsets are in-bounds — skip per-iter checks.
                    for off in self._bridge_offsets:
                        recompute(u - off)
                else:
                    for jdx, jdy in _BRIDGE_JUMPS:
                        px = ux - jdx
                        py = uy - jdy
                        if 0 <= px < w and 0 <= py <= h_minus_1:
                            recompute(py * w + px)

            if not open_heap:
                break

            # h(start, start) = 0, so calc_key(start) simplifies to (gs+km, gs)
            # whenever rhs[start] == g[start] (the termination condition).
            gs = g[start]
            if rhs[start] == gs and (gs + km, gs) <= open_heap[0][0]:
                break

    def _recompute_rhs_uniform(self, u: int) -> None:
        """Specialised _recompute_rhs for unknown_cost == 1.0.

        With unk_cost == 1.0, both `(unk_cost if arr[s]==0 else 1.0)` and
        `(diag_unk_cost if arr[s]==0 else diag_cost)` are constants, so the
        per-neighbour cost branch and the `arr` access vanish entirely.
        Bound at construction time for every planner except the return one.
        """
        if u == self._goal:
            return

        w = self._w
        h = self._h
        x = u % w
        y = u // w

        g = self._g
        blocked = self._blocked
        diag_cost = self._diag_cost

        min_rhs = _INF

        if 0 < x < w - 1 and 0 < y < h - 1:
            s = u - w  # N
            if not blocked[s]:
                v = 1.0 + g[s]
                if v < min_rhs:
                    min_rhs = v
            s = u + w  # S
            if not blocked[s]:
                v = 1.0 + g[s]
                if v < min_rhs:
                    min_rhs = v
            s = u - 1  # W
            if not blocked[s]:
                v = 1.0 + g[s]
                if v < min_rhs:
                    min_rhs = v
            s = u + 1  # E
            if not blocked[s]:
                v = 1.0 + g[s]
                if v < min_rhs:
                    min_rhs = v
            s = u - w - 1  # NW
            if not blocked[s]:
                v = diag_cost + g[s]
                if v < min_rhs:
                    min_rhs = v
            s = u - w + 1  # NE
            if not blocked[s]:
                v = diag_cost + g[s]
                if v < min_rhs:
                    min_rhs = v
            s = u + w - 1  # SW
            if not blocked[s]:
                v = diag_cost + g[s]
                if v < min_rhs:
                    min_rhs = v
            s = u + w + 1  # SE
            if not blocked[s]:
                v = diag_cost + g[s]
                if v < min_rhs:
                    min_rhs = v
        else:
            if y > 0:
                s = u - w
                if not blocked[s]:
                    v = 1.0 + g[s]
                    if v < min_rhs:
                        min_rhs = v
                if x > 0:
                    s = u - w - 1
                    if not blocked[s]:
                        v = diag_cost + g[s]
                        if v < min_rhs:
                            min_rhs = v
                if x < w - 1:
                    s = u - w + 1
                    if not blocked[s]:
                        v = diag_cost + g[s]
                        if v < min_rhs:
                            min_rhs = v
            if y < h - 1:
                s = u + w
                if not blocked[s]:
                    v = 1.0 + g[s]
                    if v < min_rhs:
                        min_rhs = v
                if x > 0:
                    s = u + w - 1
                    if not blocked[s]:
                        v = diag_cost + g[s]
                        if v < min_rhs:
                            min_rhs = v
                if x < w - 1:
                    s = u + w + 1
                    if not blocked[s]:
                        v = diag_cost + g[s]
                        if v < min_rhs:
                            min_rhs = v
            if x > 0:
                s = u - 1
                if not blocked[s]:
                    v = 1.0 + g[s]
                    if v < min_rhs:
                        min_rhs = v
            if x < w - 1:
                s = u + 1
                if not blocked[s]:
                    v = 1.0 + g[s]
                    if v < min_rhs:
                        min_rhs = v

        # NB: uniform planners never enable bridges (use_bridges currently
        # implies unknown_cost == 3.0). Dropping the dead `if self._use_bridges`
        # check shaves an attribute lookup + branch off every call.

        self._rhs[u] = min_rhs
        gu = g[u]
        if gu != min_rhs:
            g_rhs = min_rhs if min_rhs < gu else gu
            dx = self._start_x - x
            if dx < 0:
                dx = -dx
            dy = self._start_y - y
            if dy < 0:
                dy = -dy
            m = dx if dx < dy else dy
            key = (g_rhs + (dx + dy) + _SQRT2_MINUS_2 * m + self._km, g_rhs)
            heapq.heappush(self._open, (key, u))
            self._in_open[u] = 1
        else:
            self._in_open[u] = 0

    def _recompute_rhs_general(self, u: int) -> None:
        if u == self._goal:
            return

        w = self._w
        h = self._h
        x = u % w
        y = u // w

        g = self._g
        arr = self._env._array
        blocked = self._blocked
        unk_cost = self._unknown_cost
        diag_cost = self._diag_cost
        use_bridges = self._use_bridges
        diag_unk_cost = diag_cost if use_bridges else diag_cost * unk_cost

        min_rhs = _INF

        # Interior cells (the common case) skip all per-neighbour bounds
        # checks. Early-prune when g[s] >= min_rhs: since cost >= 1.0, we
        # cannot possibly beat min_rhs from such an s.
        if 0 < x < w - 1 and 0 < y < h - 1:
            s = u - w  # N
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + w  # S
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u - 1  # W
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + 1  # E
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (unk_cost if arr[s] == 0 else 1.0) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u - w - 1  # NW
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u - w + 1  # NE
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + w - 1  # SW
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                    if v < min_rhs:
                        min_rhs = v
            s = u + w + 1  # SE
            if not blocked[s]:
                gs = g[s]
                if gs < min_rhs:
                    v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                    if v < min_rhs:
                        min_rhs = v
        else:
            # Border: per-direction bounds checks.
            if y > 0:
                s = u - w  # N
                if not blocked[s]:
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v
                if x > 0:
                    s = u - w - 1  # NW
                    if not blocked[s]:
                        gs = g[s]
                        if gs < min_rhs:
                            v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                            if v < min_rhs:
                                min_rhs = v
                if x < w - 1:
                    s = u - w + 1  # NE
                    if not blocked[s]:
                        gs = g[s]
                        if gs < min_rhs:
                            v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                            if v < min_rhs:
                                min_rhs = v
            if y < h - 1:
                s = u + w  # S
                if not blocked[s]:
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v
                if x > 0:
                    s = u + w - 1  # SW
                    if not blocked[s]:
                        gs = g[s]
                        if gs < min_rhs:
                            v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                            if v < min_rhs:
                                min_rhs = v
                if x < w - 1:
                    s = u + w + 1  # SE
                    if not blocked[s]:
                        gs = g[s]
                        if gs < min_rhs:
                            v = (diag_unk_cost if arr[s] == 0 else diag_cost) + gs
                            if v < min_rhs:
                                min_rhs = v
            if x > 0:
                s = u - 1  # W
                if not blocked[s]:
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v
            if x < w - 1:
                s = u + 1  # E
                if not blocked[s]:
                    gs = g[s]
                    if gs < min_rhs:
                        v = (unk_cost if arr[s] == 0 else 1.0) + gs
                        if v < min_rhs:
                            min_rhs = v

        if use_bridges:
            bd = _BRIDGE_D
            if bd <= x < w - bd and bd <= y < h - bd:
                # All jumps land in-bounds — iterate flat offsets only.
                for off in self._bridge_offsets:
                    s = u + off
                    if not blocked[s]:
                        v = _BRIDGE_JUMP_COST + g[s]
                        if v < min_rhs:
                            min_rhs = v
            else:
                for jdx, jdy in _BRIDGE_JUMPS:
                    jx = x + jdx
                    jy = y + jdy
                    if 0 <= jx < w and 0 <= jy < h:
                        s = jy * w + jx
                        if not blocked[s]:
                            v = _BRIDGE_JUMP_COST + g[s]
                            if v < min_rhs:
                                min_rhs = v

        self._rhs[u] = min_rhs
        # Inlined _maybe_enqueue + _enqueue.
        gu = g[u]
        if gu != min_rhs:
            g_rhs = min_rhs if min_rhs < gu else gu
            dx = self._start_x - x
            if dx < 0:
                dx = -dx
            dy = self._start_y - y
            if dy < 0:
                dy = -dy
            m = dx if dx < dy else dy
            key = (g_rhs + (dx + dy) + _SQRT2_MINUS_2 * m + self._km, g_rhs)
            heapq.heappush(self._open, (key, u))
            self._in_open[u] = 1
        else:
            self._in_open[u] = 0

    def _enqueue(self, u: int) -> None:
        heapq.heappush(self._open, (self._calc_key(u), u))
        self._in_open[u] = 1

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
        h = (dx + dy) + _SQRT2_MINUS_2 * m

        return (g_rhs + h + self._km, g_rhs)

    # ---------- Helpers ----------

    def _heuristic(self, a: int, b: int) -> float:
        ax, ay = self._to_xy(a)
        bx, by = self._to_xy(b)
        dx = abs(ax - bx)
        dy = abs(ay - by)
        return (dx + dy) + _SQRT2_MINUS_2 * min(dx, dy)

    def _succ(self, u: int):
        x, y = self._to_xy(u)
        for dx, dy, cost, _ in _NEIGHBOURS:
            xx, yy = x + dx, y + dy
            if self._in_bounds(xx, yy):
                yield self._to_idx(xx, yy), cost

    def _pred(self, u: int):
        return (s for s, _ in self._succ(u))

    def _blocked_idx(self, idx: int) -> bool:
        if idx == self._start:
            return False
        return bool(self._blocked[idx])

    def _to_idx(self, x: int, y: int) -> int:
        return y * self._w + x

    def _to_xy(self, idx: int) -> tuple[int, int]:
        return idx % self._w, idx // self._w

    def _in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self._w and 0 <= y < self._h
