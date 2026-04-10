from typing import Optional
from collections import deque

from cambc import Position, Direction
from nav.space_map import (
    GotoTileRepresentation,
    sm_in_bounds,
    passable_at,
    dist_sq,
    to_sm,
    passable,
)
from grid import DIRS

# Precompute deltas to avoid repeated method calls in tight loops
_DIR_DELTAS = [(d, *d.delta()) for d in DIRS]

# Int value of AVOID for fast inline passability checks
_AVOID = int(GotoTileRepresentation.AVOID)

_INF = 1 << 30


def _bfs_toward(
    space_map: list[list[int]],
    target_sm: tuple[int, int],
    pos: Position,
    target: Position,
    visited: Optional[set[tuple[int, int]]] = None,
    blocked_first_steps: Optional[set[tuple[int, int]]] = None,
) -> Optional[Direction]:
    """BFS on the 9x9 grid from centre (4,4) toward target_sm.

    If `visited` is provided, the BFS avoids world cells that have been
    visited (except for the target cell itself). This makes the bot
    prefer fresh territory.

    If target is reachable, returns the first step of the shortest path.
    Otherwise returns the first step toward the closest reachable cell
    to target_sm.
    """
    tx, ty = target_sm
    target_in_grid = (
        0 <= tx < 9 and 0 <= ty < 9 and space_map[tx][ty] != _AVOID
    )

    # Flat arrays indexed by x*9+y for O(1) lookup without hashing
    seen = bytearray(81)
    seen[4 * 9 + 4] = 1
    first_step = [None] * 81  # stores Direction or None

    q = deque()
    q.append((4, 4))
    _pop = q.popleft
    _push = q.append

    has_blocked = blocked_first_steps is not None and len(blocked_first_steps) > 0
    has_visited = visited is not None
    pos_x, pos_y = pos.x, pos.y

    while q:
        cx, cy = _pop()
        ci = cx * 9 + cy
        if target_in_grid and cx == tx and cy == ty:
            return first_step[ci]
        fs_cur = first_step[ci]
        is_start = cx == 4 and cy == 4
        for d, ddx, ddy in _DIR_DELTAS:
            nx, ny = cx + ddx, cy + ddy
            ni = nx * 9 + ny
            # Inline bounds + seen + passability
            if nx < 0 or nx >= 9 or ny < 0 or ny >= 9:
                continue
            if seen[ni]:
                continue
            if space_map[nx][ny] == _AVOID:
                continue
            if is_start:
                if has_blocked and (nx, ny) in blocked_first_steps:
                    continue
            # If visited-aware, skip visited world cells (except target)
            if has_visited:
                wx, wy = pos_x + nx - 4, pos_y + ny - 4
                if (wx, wy) in visited:
                    if not (target_in_grid and nx == tx and ny == ty):
                        continue
            seen[ni] = 1
            first_step[ni] = fs_cur if fs_cur is not None else d
            _push((nx, ny))

    # Target not reached — head toward closest reachable cell
    best_dir = None
    best_dist = _INF
    for i in range(81):
        fs = first_step[i]
        if fs is None:
            continue
        rx, ry = i // 9, i % 9
        dist = (rx - tx) ** 2 + (ry - ty) ** 2
        if dist < best_dist:
            best_dist = dist
            best_dir = fs
    return best_dir


def _bfs_to_unvisited(
    space_map: list[list[int]],
    pos: Position,
    visited: set[tuple[int, int]],
    target: Position,
) -> Optional[Direction]:
    """BFS to the nearest unvisited passable cell, preferring closer to target."""
    seen = bytearray(81)
    seen[4 * 9 + 4] = 1
    first_step = [None] * 81

    q = deque()
    q.append((4, 4, 0))
    _pop = q.popleft
    _push = q.append

    best_dir = None
    best_bfs_dist = _INF
    best_target_dist = _INF

    pos_x, pos_y = pos.x, pos.y
    tgt_x, tgt_y = target.x, target.y

    while q:
        cx, cy, depth = _pop()
        if depth > best_bfs_dist:
            break

        ci = cx * 9 + cy
        is_start = cx == 4 and cy == 4

        if not is_start:
            wx, wy = pos_x + cx - 4, pos_y + cy - 4
            fs_cur = first_step[ci]
            if (wx, wy) not in visited and fs_cur is not None:
                td = (wx - tgt_x) ** 2 + (wy - tgt_y) ** 2
                if depth < best_bfs_dist or (
                    depth == best_bfs_dist and td < best_target_dist
                ):
                    best_bfs_dist = depth
                    best_target_dist = td
                    best_dir = fs_cur

        fs_cur = first_step[ci]
        next_depth = depth + 1
        for d, ddx, ddy in _DIR_DELTAS:
            nx, ny = cx + ddx, cy + ddy
            ni = nx * 9 + ny
            if nx < 0 or nx >= 9 or ny < 0 or ny >= 9:
                continue
            if seen[ni]:
                continue
            if space_map[nx][ny] == _AVOID:
                continue
            seen[ni] = 1
            first_step[ni] = fs_cur if fs_cur is not None else d
            _push((nx, ny, next_depth))

    return best_dir


class AlexNav:
    """Local navigator on a 9x9 vision grid.

    Core strategy:
    1. Try BFS toward target through UNVISITED cells only.
       This naturally avoids revisiting dead-end paths.
    2. If no unvisited path exists, BFS to the nearest unvisited
       cell (frontier exploration), preferring cells closer to target.
    3. If all reachable cells are visited, fall back to unrestricted
       BFS toward target.

    The visited set grows across the entire navigation to one target
    and is cleared on arrival. This simple mechanism handles concave
    obstacles, dead ends, U-traps, and spirals without needing
    explicit wall-following or oscillation detection.
    """

    def __init__(self):
        self._recent: deque = deque(maxlen=8)
        self._last_pos: Optional[tuple[int, int]] = None
        self._history: deque = deque(maxlen=24)
        self._exploring: bool = False
        self._best_dist_sq: float = float("inf")

        self._visited: set[tuple[int, int]] = set()
        self._no_progress_count: int = 0

        self.target: Optional[Position] = None

    def _is_truly_stuck(self) -> bool:
        if len(self._history) < 12:
            return False
        positions = list(self._history)
        unique = len(set(positions))
        return unique <= len(positions) // 3

    @staticmethod
    def _ranked_dirs(target_sm: tuple[int, int], space_map) -> Optional[Direction]:
        tdx, tdy = target_sm[0] - 4, target_sm[1] - 4
        best, best_dot = None, -_INF
        for d, ddx, ddy in _DIR_DELTAS:
            if space_map[4 + ddx][4 + ddy] != _AVOID:
                dot = tdx * ddx + tdy * ddy
                if dot > best_dot:
                    best_dot, best = dot, d
        return best

    def plan(
        self,
        pos: Position,
        target: Position,
        space_map: list[list[GotoTileRepresentation]],
    ) -> tuple[Optional[Direction], Optional[str]]:
        self.target = target

        pos_x, pos_y = pos.x, pos.y
        tgt_x, tgt_y = target.x, target.y

        if pos_x == tgt_x and pos_y == tgt_y:
            self._recent.clear()
            self._last_pos = None
            self._history.clear()
            self._exploring = False
            self._best_dist_sq = float("inf")
            self._visited.clear()
            self._no_progress_count = 0
            return Direction.CENTRE, None

        target_sm = to_sm(pos, target)
        tsx, tsy = target_sm
        if (
            0 <= tsx < 9
            and 0 <= tsy < 9
            and space_map[tsx][tsy] == _AVOID
        ):
            return None, "target is impassable"

        pos_tup = (pos_x, pos_y)
        self._history.append(pos_tup)
        self._visited.add(pos_tup)

        # Track progress
        cur_dist = (pos_x - tgt_x) ** 2 + (pos_y - tgt_y) ** 2
        if cur_dist < self._best_dist_sq:
            self._best_dist_sq = cur_dist
            self._no_progress_count = 0
        else:
            self._no_progress_count += 1

        oscillating = pos_tup in self._recent

        # Use visited-aware navigation once we detect any trouble
        use_visited = (
            oscillating
            or self._no_progress_count >= 3
            or self._exploring
            or self._is_truly_stuck()
        )

        if use_visited:
            self._exploring = True

        # Exit exploration on sustained progress
        if self._exploring and self._no_progress_count == 0 and not oscillating:
            self._exploring = False
            use_visited = False

        # ── Primary: BFS toward target avoiding visited cells ─────
        if use_visited:
            # First try: BFS toward target through unvisited cells
            step = _bfs_toward(space_map, target_sm, pos, target, self._visited)
            if step is not None:
                self._recent.append(pos_tup)
                self._last_pos = pos_tup
                return step, None

            # Second try: BFS to nearest unvisited cell (exploration)
            step = _bfs_to_unvisited(space_map, pos, self._visited, target)
            if step is not None:
                self._recent.append(pos_tup)
                self._last_pos = pos_tup
                return step, None

            # Third: BFS away from target to escape dead ends
            anti_sm = (4 - (tsx - 4), 4 - (tsy - 4))
            step = _bfs_toward(space_map, anti_sm, pos, target)
            if step is not None:
                self._recent.append(pos_tup)
                self._last_pos = pos_tup
                return step, None

            # Fourth: unrestricted BFS toward target
            step = _bfs_toward(space_map, target_sm, pos, target)
            if step is not None:
                self._recent.append(pos_tup)
                self._last_pos = pos_tup
                return step, None

            return None, "surrounded"

        # ── Greedy ────────────────────────────────────────────────
        desired = pos.direction_to(target)
        dx, dy = desired.delta()

        if 0 <= 4 + dx < 9 and 0 <= 4 + dy < 9 and space_map[4 + dx][4 + dy] != _AVOID:
            self._recent.append(pos_tup)
            self._last_pos = pos_tup
            return desired, None

        # ── Ranked fallback ───────────────────────────────────────
        fallback = self._ranked_dirs(target_sm, space_map)
        if fallback is not None:
            fdx, fdy = fallback.delta()
            tdx, tdy = tsx - 4, tsy - 4
            if tdx * fdx + tdy * fdy > 0:
                self._recent.append(pos_tup)
                self._last_pos = pos_tup
                return fallback, None

        # ── BFS toward target ─────────────────────────────────────
        blocked: set[tuple[int, int]] = set()
        if self._last_pos is not None:
            lx, ly = self._last_pos
            sx, sy = lx - pos_x + 4, ly - pos_y + 4
            if 0 <= sx < 9 and 0 <= sy < 9:
                blocked.add((sx, sy))

        bfs_dir = _bfs_toward(
            space_map, target_sm, pos, target, blocked_first_steps=blocked
        )
        if bfs_dir is not None:
            self._recent.append(pos_tup)
            self._last_pos = pos_tup
            return bfs_dir, None

        bfs_dir = _bfs_toward(space_map, target_sm, pos, target)
        if bfs_dir is not None:
            self._recent.append(pos_tup)
            self._last_pos = pos_tup
            return bfs_dir, None

        return None, "surrounded"
