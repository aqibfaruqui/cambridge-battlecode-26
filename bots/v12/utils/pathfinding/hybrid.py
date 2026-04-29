"""HybridPath: BugPath with an in-the-background D* Lite path.

Each round we spend a slice of CPU advancing D* Lite incrementally, capped
at an absolute round-elapsed deadline (default 800us, leaving headroom
under the 2ms TLE). The cap is on the round-wide CPU clock, so every D*
compute call in the round shares one budget pool — no matter how many
HybridPath methods or instances trigger drains, total D* CPU per round
is bounded by one deadline.

When D* has produced a complete path that's still valid for the bot's
current position and current map state, we return moves along that path.
Otherwise we fall back to BugPath.

Same surface API as DStarLite/BugPath so callers can swap in.
"""

from __future__ import annotations

from typing import Callable

from cambc import Direction

from utils.map.raw_map_representation import EnvironmentMap
from utils.pathfinding.bug import BugPath
from utils.pathfinding.d_star import DStarLite, _DEFAULT_BLOCK_MASK


_DEFAULT_DEADLINE_US = 1200

_DELTA_TO_DIR = {
    (0, -1): Direction.NORTH,
    (1, -1): Direction.NORTHEAST,
    (1, 0): Direction.EAST,
    (1, 1): Direction.SOUTHEAST,
    (0, 1): Direction.SOUTH,
    (-1, 1): Direction.SOUTHWEST,
    (-1, 0): Direction.WEST,
    (-1, -1): Direction.NORTHWEST,
}


class HybridPath:
    __slots__ = (
        "_env",
        "_w",
        "_bug",
        "_dstar",
        "_goal_x",
        "_goal_y",
        "_cached_path",
        "_cache_dirty",
    )

    def __init__(
        self,
        env: EnvironmentMap,
        goal_x: int,
        goal_y: int,
        *,
        time_fn: Callable[[], int],
        block_mask: int = _DEFAULT_BLOCK_MASK,
        unknown_cost: float = 1.0,
        use_bridges: bool = False,
        cpu_deadline_us: int = _DEFAULT_DEADLINE_US,
    ):
        self._env = env
        self._w = env._w
        self._bug = BugPath(
            env,
            goal_x,
            goal_y,
            block_mask=block_mask,
            unknown_cost=unknown_cost,
            use_bridges=use_bridges,
        )
        # Absolute round-elapsed deadline: every _compute_shortest_path call
        # in this round bails when time_fn() (round-wide CPU clock) crosses
        # cpu_deadline_us. Multiple compute calls in one round share the cap,
        # so total D* CPU per round is bounded by one budget — no matter how
        # many drain triggers fire (notify, set_dyn, step) or how many
        # HybridPath instances run on the same bot.
        self._dstar = DStarLite(
            env,
            goal_x,
            goal_y,
            block_mask=block_mask,
            unknown_cost=unknown_cost,
            use_bridges=use_bridges,
            cpu_budget_us=cpu_deadline_us,  # ignored while external deadline is set
            time_fn=time_fn,
            # extract_path needs consistent g along the full path, not just
            # at start; opt out of D* Lite's early-termination optimization.
            eager_drain=True,
        )
        # time_fn (get_cpu_time_elapsed) resets per round, so this single
        # absolute value is correct for every round — no per-round refresh.
        self._dstar.set_deadline(cpu_deadline_us)

        self._goal_x = goal_x
        self._goal_y = goal_y
        # Path from current position to goal, valid as of last completed plan.
        self._cached_path: list[tuple[int, int]] | None = None
        # Set when map/blocker state changes after the cache was extracted —
        # forces a tail walkability re-check on next use.
        self._cache_dirty = False

    # ---------- Public API (mirrors DStarLite/BugPath) ----------

    def set_goal(self, gx: int, gy: int) -> None:
        if gx == self._goal_x and gy == self._goal_y:
            return
        self._bug.set_goal(gx, gy)
        self._dstar.set_goal(gx, gy)
        self._goal_x = gx
        self._goal_y = gy
        self._cached_path = None
        self._cache_dirty = False

    def set_position(self, sx: int, sy: int) -> None:
        self._bug.set_position(sx, sy)
        self._dstar.set_position(sx, sy)

    def notify_map_changes(self) -> bool:
        b = self._bug.notify_map_changes()
        d = self._dstar.notify_map_changes()
        if b or d:
            self._cache_dirty = True
        return b or d

    def set_dynamic_blockers(self, blocked_xy: list[tuple[int, int]]) -> bool:
        b = self._bug.set_dynamic_blockers(blocked_xy)
        d = self._dstar.set_dynamic_blockers(blocked_xy)
        if b or d:
            self._cache_dirty = True
        return b or d

    def plan(self) -> None:
        self._validate_cache()
        self._dstar.plan()
        self._maybe_refresh_cache()

    def step(self) -> Direction | None:
        self._validate_cache()
        self._dstar.plan()
        self._maybe_refresh_cache()
        d = self._cached_step_dir()
        if d is not None:
            return d
        return self._bug.step()

    def step_xy(self) -> tuple[int, int] | None:
        self._validate_cache()
        self._dstar.plan()
        self._maybe_refresh_cache()
        nxt = self._cached_step_xy()
        if nxt is not None:
            return nxt
        return self._bug.step_xy()

    def extract_path(self) -> list[tuple[int, int]]:
        """Return the cached D* path from current position to goal, or []
        if no valid cached path is available. Validates lazily — may drop
        the cache if it has become stale."""
        self._validate_cache()
        path = self._cached_path
        if path is None:
            return []
        idx = self._find_position_on_path()
        if idx is None:
            return []
        return path[idx:]

    def extract_path_lines(self) -> list[tuple[int, int, int, int]]:
        pts = self.extract_path()
        return [
            (pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1])
            for i in range(len(pts) - 1)
        ]

    @property
    def last_completed(self) -> bool:
        """True iff D* has a fully drained plan from the current state."""
        return self._dstar.last_completed

    @property
    def using_dstar(self) -> bool:
        """True iff a valid cached D* path is available right now. Cheap;
        no compute. Does not mutate state — pure peek."""
        path = self._cached_path
        if path is None:
            return False
        idx = self._find_position_on_path()
        if idx is None:
            return False
        if self._cache_dirty and not self._validate_tail(idx):
            return False
        return True

    # ---------- Internals ----------

    def _validate_cache(self) -> None:
        """Drop the cache if it's no longer usable for the current state.
        Runs at the start of every drive call so subsequent _maybe_refresh
        only fires when truly needed."""
        path = self._cached_path
        if path is None:
            return
        idx = self._find_position_on_path()
        if idx is None:
            self._cached_path = None
            self._cache_dirty = False
            return
        if self._cache_dirty:
            if not self._validate_tail(idx):
                self._cached_path = None
                self._cache_dirty = False
                return
            self._cache_dirty = False

    def _maybe_refresh_cache(self) -> None:
        """If we have no cache and D* just produced a complete plan, extract
        the path and announce it. Print fires exactly when the cache flips
        from absent to present, which is the "we just finished computing"
        moment the caller asked about."""
        if self._cached_path is not None:
            return
        if not self._dstar.last_completed:
            return
        path = self._dstar.extract_path()
        if not path:
            return
        self._cached_path = path
        self._cache_dirty = False
        print(f"[HybridPath] D* path computed: {len(path)} cells to ({self._goal_x},{self._goal_y})")

    def _find_position_on_path(self) -> int | None:
        path = self._cached_path
        if path is None:
            return None
        cur = (self._dstar._start % self._w, self._dstar._start // self._w)
        # Linear scan — paths are short (< ~80 cells in practice).
        for i, p in enumerate(path):
            if p == cur:
                return i
        return None

    def _validate_tail(self, idx: int) -> bool:
        """Verify path[idx:] cells are still walkable under current state.
        Uses D*'s own _is_blocked so the check matches the planner's view
        (treats current start as walkable, etc.)."""
        path = self._cached_path
        if path is None:
            return False
        is_blocked = self._dstar._is_blocked
        w = self._w
        for x, y in path[idx:]:
            if is_blocked(y * w + x):
                return False
        return True

    def _cached_step_xy(self) -> tuple[int, int] | None:
        """Assumes _validate_cache has just run, so the cache (if present)
        is valid for the current position."""
        path = self._cached_path
        if path is None:
            return None
        idx = self._find_position_on_path()
        if idx is None:
            return None
        if idx + 1 >= len(path):
            return path[idx]  # at goal
        return path[idx + 1]

    def _cached_step_dir(self) -> Direction | None:
        nxt = self._cached_step_xy()
        if nxt is None:
            return None
        cur_x = self._dstar._start % self._w
        cur_y = self._dstar._start // self._w
        dx = nxt[0] - cur_x
        dy = nxt[1] - cur_y
        if dx == 0 and dy == 0:
            return Direction.CENTRE
        # Bridge jumps (|dx|>1 or |dy|>1) aren't representable as a unit
        # Direction; callers using bridges must use step_xy.
        return _DELTA_TO_DIR.get((dx, dy))
