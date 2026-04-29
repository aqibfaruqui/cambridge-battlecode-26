"""
Bug-style pathfinder with the same public API as DStarLite.

This is a stateful, single-step planner: `step()` returns the next move
direction by trying a greedy step toward the goal and falling back to
obstacle-following when blocked. Unlike D* Lite there is no precomputed
g-table — methods that only make sense for a graph-search planner
(`plan`, `extract_path`, `extract_path_lines`) are kept as no-ops so
this class is drop-in interchangeable.

Mirrors the EnvironmentMap + dynamic-blocker pattern used by
`d_star.DStarLite`: tile blockedness is derived from a static block_mask
applied to env._array plus a runtime set of dynamic blockers.
"""

from __future__ import annotations

from cambc import Direction

from utils.map.raw_map_representation import EnvironmentMap


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

# Clockwise from N. Matches d_star.py's y-down convention (NORTH=(0,-1)).
# Index in this tuple is the rotation slot: +1 == rotate_right (45° CW),
# -1 == rotate_left.
_DIRS_8: tuple[tuple[int, int, Direction], ...] = (
    (0, -1, Direction.NORTH),
    (1, -1, Direction.NORTHEAST),
    (1, 0, Direction.EAST),
    (1, 1, Direction.SOUTHEAST),
    (0, 1, Direction.SOUTH),
    (-1, 1, Direction.SOUTHWEST),
    (-1, 0, Direction.WEST),
    (-1, -1, Direction.NORTHWEST),
)

MAX_TURNS_MOVING_TO_OBSTACLE = 2
MIN_DIST_RESET_SQ = 9  # MIN_DIST_RESET=3 in the original, squared for cheap compare.


def _dir_idx(dx: int, dy: int) -> int:
    """Snap an (dx, dy) offset to the nearest of 8 compass directions."""
    if dx == 0 and dy == 0:
        return 0
    sx = (dx > 0) - (dx < 0)
    sy = (dy > 0) - (dy < 0)
    adx = -dx if dx < 0 else dx
    ady = -dy if dy < 0 else dy
    # >2.414 ratio (tan(67.5°)) snaps to a cardinal; otherwise diagonal.
    # Cheap integer approximation: use 2× threshold.
    if adx > ady * 2:
        sy = 0
    elif ady > adx * 2:
        sx = 0
    # Map (sx, sy) -> index in _DIRS_8.
    return _OFFSET_TO_IDX[(sx, sy)]


_OFFSET_TO_IDX = {(dx, dy): i for i, (dx, dy, _) in enumerate(_DIRS_8)}


class BugPath:
    __slots__ = (
        "_env",
        "_w",
        "_h",
        "_n",
        "_block_mask",
        "_blocked",
        "_dynamic_blocked",
        "_snapshot",
        "_start",
        "_start_x",
        "_start_y",
        "_goal",
        "_goal_x",
        "_goal_y",
        "_states",
        "_bug_path_index",
        "_rotate_right",
        "_last_obstacle",
        "_min_dist_sq",
        "_min_loc",
        "_turns_moving_to_obstacle",
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
        del unknown_cost, use_bridges  # API parity with DStarLite; bug nav has no edge costs.
        self._env = env
        self._w = env._w
        self._h = env._h
        self._n = self._w * self._h
        self._block_mask = block_mask

        self._goal_x = goal_x
        self._goal_y = goal_y
        self._goal = goal_y * self._w + goal_x

        # Start is unknown until set_position; default to goal so step() at
        # init returns CENTRE rather than blowing up. d_star.py uses the same
        # default.
        self._start = self._goal
        self._start_x = goal_x
        self._start_y = goal_y

        self._snapshot = bytearray(env._array)
        self._dynamic_blocked: set[int] = set()
        self._blocked = bytearray(self._n)
        arr = env._array
        mask = block_mask
        blocked = self._blocked
        for i in range(self._n):
            if (mask >> arr[i]) & 1:
                blocked[i] = 1
        blocked[self._start] = 0  # match d_star invariant: current cell is walkable

        # Per-tile state hash for cycle detection. One int per cell —
        # flat list rather than 2D for cheaper indexing in the hot path.
        self._states: list[int] = [0] * self._n

        self._bug_path_index: int = 0
        self._rotate_right: bool | None = None
        self._last_obstacle: int | None = None
        self._min_dist_sq: int = 1 << 30
        self._min_loc: int | None = None
        self._turns_moving_to_obstacle: int = 0

    # ---------- Public API (mirrors DStarLite) ----------

    def set_goal(self, gx: int, gy: int) -> None:
        new_goal = gy * self._w + gx
        if new_goal == self._goal:
            return

        # Soft vs hard reset, mirroring the original BugPath.move_to logic
        # that compared targets — keep min-progress info if the new goal is
        # close to the previous one, full reset if far.
        ddx = gx - self._goal_x
        ddy = gy - self._goal_y
        dist_sq = ddx * ddx + ddy * ddy

        self._goal = new_goal
        self._goal_x = gx
        self._goal_y = gy

        if dist_sq >= MIN_DIST_RESET_SQ:
            self._rotate_right = None
            self._reset_pathfinding()
        else:
            self._soft_reset()

    def set_position(self, sx: int, sy: int) -> None:
        new_start = sy * self._w + sx
        old_start = self._start
        if new_start == old_start:
            return

        # Restore old_start's true blocked state.
        arr = self._env._array
        mask = self._block_mask
        dyn = self._dynamic_blocked
        blocked = self._blocked
        if ((mask >> arr[old_start]) & 1) or (old_start in dyn):
            blocked[old_start] = 1

        # Force new_start walkable so a bot standing on a dynamic blocker
        # (e.g. on top of an ally just placed) can still plan an exit.
        blocked[new_start] = 0

        self._start = new_start
        self._start_x = sx
        self._start_y = sy

    def notify_map_changes(self) -> bool:
        """Refresh the cached `_blocked` bitmap from env._array.

        Bug nav doesn't precompute paths so there's nothing to invalidate
        beyond the per-cell blocked bit. Returns True iff anything changed,
        matching DStarLite's contract.
        """
        arr = self._env._array
        snapshot = self._snapshot
        if arr == snapshot:
            return False

        n = self._n
        blocked = self._blocked
        dyn = self._dynamic_blocked
        mask = self._block_mask
        current_start = self._start

        i = 0
        changed = False
        while i < n:
            if arr[i] != snapshot[i]:
                changed = True
                new_val = arr[i]
                snapshot[i] = new_val
                if i == current_start:
                    blocked[i] = 0
                elif (mask >> new_val) & 1 or i in dyn:
                    blocked[i] = 1
                else:
                    blocked[i] = 0
            i += 1

        # Map changed -> our memory of where we were stuck may be stale.
        # Drop obstacle tracking so the next step() retries greedy.
        if changed:
            self._last_obstacle = None
            self._turns_moving_to_obstacle = 0

        return changed

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

        blocked = self._blocked
        arr = self._env._array
        mask = self._block_mask
        current_start = self._start

        for idx in changed_nodes:
            if idx == current_start:
                blocked[idx] = 0
            elif (mask >> arr[idx]) & 1:
                blocked[idx] = 1
            elif idx in new_blocked:
                blocked[idx] = 1
            else:
                blocked[idx] = 0

        # New blockers may invalidate the obstacle we were tracking; drop it.
        self._last_obstacle = None
        self._turns_moving_to_obstacle = 0
        return True

    def step(self) -> Direction | None:
        if self._start == self._goal:
            return Direction.CENTRE

        sx = self._start_x
        sy = self._start_y
        gx = self._goal_x
        gy = self._goal_y
        ddx = gx - sx
        ddy = gy - sy
        d_sq = ddx * ddx + ddy * ddy

        # Cycle detection — if we revisit a tile in the same bug-state, we're
        # looping; drop obstacle memory and try fresh.
        self._check_state()

        # Closer than ever -> made progress, clear obstacle tracking.
        if d_sq < self._min_dist_sq:
            self._min_dist_sq = d_sq
            self._min_loc = self._start
            self._reset_pathfinding()

        # Try greedy step toward goal when no obstacle is being tracked.
        if self._last_obstacle is None:
            greedy = self._greedy_step(ddx, ddy)
            if greedy is not None:
                return greedy

        # Obstacle-following: rotate around the wall.
        if self._last_obstacle is not None:
            ox = self._last_obstacle % self._w
            oy = self._last_obstacle // self._w
            base_idx = _dir_idx(ox - sx, oy - sy)
        else:
            base_idx = _dir_idx(ddx, ddy)

        if self._rotate_right is None:
            self._choose_rotation(base_idx)

        cur_idx = base_idx
        rotate = 1 if self._rotate_right else -1
        # Up to 2 full sweeps (16 attempts) so we can flip direction at a
        # map edge and try the other way around.
        for _ in range(16):
            dx, dy, direction = _DIRS_8[cur_idx]
            nx = sx + dx
            ny = sy + dy
            if 0 <= nx < self._w and 0 <= ny < self._h:
                ni = ny * self._w + nx
                if not self._blocked[ni]:
                    # If we were tracking an obstacle, count consecutive
                    # turns where we managed to step "toward" it (i.e. we
                    # think we're escaping but the obstacle memory may be
                    # stale). Reset when we've done it enough times.
                    if self._last_obstacle is not None:
                        target_idx = _dir_idx(
                            (self._last_obstacle % self._w) - sx,
                            (self._last_obstacle // self._w) - sy,
                        )
                        if cur_idx == target_idx:
                            self._turns_moving_to_obstacle += 1
                            if self._turns_moving_to_obstacle >= MAX_TURNS_MOVING_TO_OBSTACLE:
                                self._reset_pathfinding()
                    return direction
                # Blocked but on-map => this is our newest obstacle.
                self._last_obstacle = ni
            else:
                # Hit map edge: flip rotation direction and retry.
                self._rotate_right = not self._rotate_right
                rotate = -rotate
            cur_idx = (cur_idx + rotate) % 8

        return None

    def step_xy(self) -> tuple[int, int] | None:
        d = self.step()
        if d is None:
            return None
        if d == Direction.CENTRE:
            return (self._start_x, self._start_y)
        for dx, dy, direction in _DIRS_8:
            if direction == d:
                return (self._start_x + dx, self._start_y + dy)
        return None

    def plan(self) -> None:
        """No-op. Bug nav decides moves lazily in step()."""

    def extract_path(self) -> list[tuple[int, int]]:
        """No-op. Bug nav has no precomputed path; always returns []."""
        return []

    def extract_path_lines(self) -> list[tuple[int, int, int, int]]:
        """No-op. See extract_path."""
        return []

    # ---------- Internals ----------

    def _greedy_step(self, ddx: int, ddy: int) -> Direction | None:
        """Try direct dir; if blocked, try the two adjacent diagonals iff
        either strictly reduces squared distance to the goal."""
        sx = self._start_x
        sy = self._start_y
        w = self._w
        h = self._h
        blocked = self._blocked

        base = _dir_idx(ddx, ddy)
        dx, dy, direction = _DIRS_8[base]
        nx = sx + dx
        ny = sy + dy
        if 0 <= nx < w and 0 <= ny < h and not blocked[ny * w + nx]:
            return direction

        cur_dist = ddx * ddx + ddy * ddy
        best_dir: Direction | None = None
        best_dist = cur_dist
        # ±45° neighbours.
        for off in (1, -1):
            idx = (base + off) % 8
            dx, dy, direction = _DIRS_8[idx]
            nx = sx + dx
            ny = sy + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            if blocked[ny * w + nx]:
                continue
            ndx = self._goal_x - nx
            ndy = self._goal_y - ny
            nd = ndx * ndx + ndy * ndy
            if nd < best_dist:
                best_dist = nd
                best_dir = direction
        return best_dir

    def _choose_rotation(self, base_idx: int) -> None:
        """Sweep both ways from `base_idx` to find the first walkable
        direction on each side; pick whichever lands closer to the goal."""
        sx = self._start_x
        sy = self._start_y
        w = self._w
        h = self._h
        blocked = self._blocked
        gx = self._goal_x
        gy = self._goal_y

        def _sweep(rotate: int) -> tuple[int, int] | None:
            idx = base_idx
            for _ in range(8):
                dx, dy, _ = _DIRS_8[idx]
                nx = sx + dx
                ny = sy + dy
                if 0 <= nx < w and 0 <= ny < h and not blocked[ny * w + nx]:
                    return (nx, ny)
                idx = (idx + rotate) % 8
            return None

        right_xy = _sweep(1)
        left_xy = _sweep(-1)

        right_d = (
            (right_xy[0] - gx) ** 2 + (right_xy[1] - gy) ** 2
            if right_xy is not None
            else 1 << 30
        )
        left_d = (
            (left_xy[0] - gx) ** 2 + (left_xy[1] - gy) ** 2
            if left_xy is not None
            else 1 << 30
        )
        self._rotate_right = right_d < left_d

    def _reset_pathfinding(self) -> None:
        self._last_obstacle = None
        self._bug_path_index += 1
        self._turns_moving_to_obstacle = 0
        # Don't clear _min_dist_sq here — the original Java preserved it on
        # obstacle resets; only set_goal/_soft_reset touches it.

    def _soft_reset(self) -> None:
        if self._min_loc is not None:
            mlx = self._min_loc % self._w
            mly = self._min_loc // self._w
            ddx = mlx - self._goal_x
            ddy = mly - self._goal_y
            self._min_dist_sq = ddx * ddx + ddy * ddy
        else:
            self._min_dist_sq = 1 << 30
            self._reset_pathfinding()

    def _check_state(self) -> int:
        """Hash (bug_path_index, last_obstacle, rotate_dir) per tile.
        Reset if we revisit a tile in the same state."""
        last = self._last_obstacle if self._last_obstacle is not None else self._n
        rot = 0 if self._rotate_right is None else (1 if self._rotate_right else 2)
        # Pack into a single int. _n fits in ~14 bits for typical maps; bug_path_index
        # can be large but Python ints handle it fine.
        state = (self._bug_path_index << 18) | (last << 2) | rot

        if self._states[self._start] == state:
            self._reset_pathfinding()
        self._states[self._start] = state
        return state
