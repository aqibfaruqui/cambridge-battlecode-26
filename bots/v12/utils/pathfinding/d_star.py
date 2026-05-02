import heapq
import math
from collections.abc import Callable
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
DSTAR_CPU_DEADLINE_US = 1600

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
# Like _RETURN_BLOCK_MASK but allows UNKNOWN and ore tiles. Seek bots can step
# onto ore so the placement state can ring conveyors, step off, and build.
_SEEK_BLOCK_MASK = (
    (1 << _WALL)
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
        "_compute_paused",
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
        self._blocked = bytearray(self._n)
        arr = env._array
        mask = self._block_mask
        blocked = self._blocked
        for i in range(self._n):
            if (mask >> arr[i]) & 1:
                blocked[i] = 1
        blocked[self._start] = 0  # force-walkable invariant for current position
        self._unknown_cost = unknown_cost
        self._use_bridges = use_bridges
        self._diag_cost = _BRIDGE_JUMP_COST if use_bridges else _SQRT2
        self._compute_paused = False

    # ---------- Public API ----------

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

    def notify_map_changes(
        self,
        deadline_us: int | None = None,
        get_time_us: Callable[[], int] | None = None,
    ) -> bool:
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
                    for jdx, jdy in _BRIDGE_JUMPS:
                        px = x - jdx
                        py = y - jdy
                        if 0 <= px < w and 0 <= py < h:
                            recompute(py * w + px)

            i += 1

        self._compute_shortest_path(deadline_us, get_time_us)
        return True

    def set_dynamic_blockers(
        self,
        blocked_xy: list[tuple[int, int]],
        deadline_us: int | None = None,
        get_time_us: Callable[[], int] | None = None,
    ) -> bool:
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
            self._compute_shortest_path(deadline_us, get_time_us)

        return True

    def step(
        self,
        deadline_us: int | None = None,
        get_time_us: Callable[[], int] | None = None,
    ) -> Direction | None:
        if self._start == self._goal:
            return Direction.CENTRE

        if deadline_us is not None and get_time_us is not None and get_time_us() >= deadline_us:
            return None

        if not self._compute_shortest_path(deadline_us, get_time_us):
            return None

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

    def step_xy(
        self,
        deadline_us: int | None = None,
        get_time_us: Callable[[], int] | None = None,
    ) -> tuple[int, int] | None:
        """Like step(), but returns (x, y) of the next cell.
        When use_bridges=True this can return a cell at bridge-jump distance."""
        if self._start == self._goal:
            return (self._goal % self._w, self._goal // self._w)

        if deadline_us is not None and get_time_us is not None and get_time_us() >= deadline_us:
            return None

        if not self._compute_shortest_path(deadline_us, get_time_us):
            return None

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

    def planning_pending(self) -> bool:
        return self._compute_paused

    # ---------- Core D* Lite ----------

    def _compute_shortest_path(
        self,
        deadline_us: int | None = None,
        get_time_us: Callable[[], int] | None = None,
    ) -> bool:
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
        checks = 0
        check_budget = deadline_us is not None and get_time_us is not None

        while open_heap:
            if check_budget and (checks & 7) == 0 and get_time_us() >= deadline_us:
                self._compute_paused = True
                return False
            checks += 1

            k_old, u = heapq.heappop(open_heap)

            if not in_open[u]:
                continue

            gu = g[u]
            ru = rhs[u]

            # Consistent stale entry: skip without polluting g[u]. Without this
            # the canonical else-branch below set g[u]=INF for a consistent u,
            # cascading spurious updates before the next recompute corrected it.
            if gu == ru:
                in_open[u] = False
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
            if k_old < (k_new_primary, g_rhs):
                heapq.heappush(open_heap, ((k_new_primary, g_rhs), u))
                continue

            in_open[u] = False

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

        self._compute_paused = False
        return True

    def _recompute_rhs(self, u: int) -> None:
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
        diag_unk_cost = diag_cost if self._use_bridges else diag_cost * unk_cost

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

        if self._use_bridges:
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
            self._in_open[u] = True
        else:
            # Consistent: invalidate any stale open-heap entry. The entry
            # remains in the heap (lazy deletion), but in_open[u]=False makes
            # it skip on pop, avoiding redundant processing.
            self._in_open[u] = False

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
        h = (dx + dy) + _SQRT2_MINUS_2 * m

        return (g_rhs + h + self._km, g_rhs)

    # ---------- Helpers ----------

    def _to_idx(self, x: int, y: int) -> int:
        return y * self._w + x
