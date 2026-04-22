"""Standalone tests for the D* Lite jump variant.

Run: uv run scripts/test_d_star_jump.py
Exits 0 if all tests pass, 1 on first failure.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bots" / "v11"))

from utils.map.raw_map_representation import (  # noqa: E402
    EnvironmentMap,
    TRAVERSABLE,
    WALL,
)
from utils.pathfinding.d_star import DStarLite  # noqa: E402

_INF = float("inf")


def _make_env(width: int, height: int, walls: list[tuple[int, int]] | None = None) -> EnvironmentMap:
    """Build an EnvironmentMap with all cells TRAVERSABLE except the given walls."""
    env = EnvironmentMap(width, height)
    for i in range(width * height):
        env._array[i] = TRAVERSABLE
    if walls:
        for (x, y) in walls:
            env._array[y * width + x] = WALL
    return env


# -------- Tests --------

def test_construction_both_modes():
    env = _make_env(10, 10)
    walk = DStarLite(env, 9, 9)
    assert walk._allow_jumps is False
    assert walk._jump_cost == 5.0

    jump = DStarLite(env, 9, 9, allow_jumps=True)
    assert jump._allow_jumps is True
    assert jump._jump_cost == 5.0

    custom = DStarLite(env, 9, 9, allow_jumps=True, jump_cost=7.5)
    assert custom._jump_cost == 7.5


def test_step_raises_in_jump_mode():
    env = _make_env(10, 10)
    jump = DStarLite(env, 9, 9, allow_jumps=True)
    jump.set_position(0, 0)
    jump.plan()
    try:
        jump.step()
    except RuntimeError as exc:
        assert "allow_jumps" in str(exc), f"unexpected message: {exc}"
        return
    assert False, "expected RuntimeError from step() in jump mode"


def test_step_works_in_walk_mode():
    env = _make_env(10, 10)
    walk = DStarLite(env, 9, 9)
    walk.set_position(0, 0)
    direction = walk.step()
    assert direction is not None, "walk mode should return a Direction"


def test_recompute_rhs_jump_enables_reachability():
    width, height = 5, 3
    walls = [(2, y) for y in range(height)]
    env = _make_env(width, height, walls=walls)

    walk = DStarLite(env, 4, 1)
    walk.set_position(0, 1)
    walk.plan()
    assert walk._g[walk._start] == _INF, (
        f"walk-only should be unreachable, got g={walk._g[walk._start]}"
    )

    jump = DStarLite(env, 4, 1, allow_jumps=True)
    jump.set_position(0, 1)
    jump.plan()
    assert jump._g[jump._start] != _INF, (
        f"jump mode should reach via (0,1)->(3,1)->(4,1), got g={jump._g[jump._start]}"
    )


def test_extract_path_returns_jump_segment():
    width, height = 5, 3
    walls = [(2, y) for y in range(height)]
    env = _make_env(width, height, walls=walls)

    jump = DStarLite(env, 4, 1, allow_jumps=True)
    jump.set_position(0, 1)
    jump.plan()
    path = jump.extract_path()
    assert path, f"expected a non-empty path, got {path}"
    has_jump = any(
        max(abs(path[i + 1][0] - path[i][0]), abs(path[i + 1][1] - path[i][1])) > 1
        for i in range(len(path) - 1)
    )
    assert has_jump, f"expected a jump segment in path, got {path}"


def test_notify_map_changes_updates_jump_predecessors():
    width, height = 8, 3
    env = _make_env(width, height)

    jump = DStarLite(env, 7, 1, allow_jumps=True)
    jump.set_position(0, 1)
    jump.plan()
    path_before = jump.extract_path()
    assert path_before, f"expected initial path, got {path_before}"
    # Open map — path should be all walk steps.
    assert all(
        max(abs(path_before[i + 1][0] - path_before[i][0]),
            abs(path_before[i + 1][1] - path_before[i][1])) == 1
        for i in range(len(path_before) - 1)
    ), f"expected walk-only initial path, got {path_before}"

    # Drop in a wall column across x=3, 4 (leaving x=2 passable as fallback for walk route).
    for x in (3, 4):
        for y in range(height):
            env._array[y * width + x] = WALL

    changed = jump.notify_map_changes()
    assert changed, "notify_map_changes should report changes"

    path_after = jump.extract_path()
    assert path_after, f"expected path after wall insertion, got {path_after}"
    has_jump = any(
        max(abs(path_after[i + 1][0] - path_after[i][0]),
            abs(path_after[i + 1][1] - path_after[i][1])) > 1
        for i in range(len(path_after) - 1)
    )
    assert has_jump, f"expected jump segment after wall insertion, got {path_after}"


def test_set_dynamic_blockers_updates_jump_predecessors():
    width, height = 5, 3
    walls = [(2, y) for y in range(height)]
    env = _make_env(width, height, walls=walls)

    jump = DStarLite(env, 4, 1, allow_jumps=True)
    jump.set_position(0, 1)
    jump.plan()
    assert jump._g[jump._start] != _INF, "baseline jump route should exist"

    # Block the goal (4,1) itself as a dynamic blocker — every edge into
    # the goal dies and g[start] becomes infinity.
    jump.set_dynamic_blockers([(4, 1)])

    assert jump._g[jump._start] == _INF, (
        f"blocking goal endpoint should make it unreachable, got g={jump._g[jump._start]}"
    )


def test_walk_preferred_when_cheaper():
    env = _make_env(10, 10)
    jump = DStarLite(env, 3, 0, allow_jumps=True)
    jump.set_position(0, 0)
    jump.plan()
    path = jump.extract_path()
    assert path == [(0, 0), (1, 0), (2, 0), (3, 0)], (
        f"expected all-walk path on open map, got {path}"
    )


def test_jump_passes_through_wall():
    # 5x1: start (0,0), wall (2,0), goal (4,0). Walk is blocked at (2,0).
    # Jump (0,0)->(3,0): dist_sq=9, endpoint traversable, passes through the wall.
    env = _make_env(5, 1, walls=[(2, 0)])
    jump = DStarLite(env, 4, 0, allow_jumps=True)
    jump.set_position(0, 0)
    jump.plan()
    assert jump._g[jump._start] != _INF, (
        f"jump should pass through wall at (2,0), got g={jump._g[jump._start]}"
    )


def test_jump_passes_through_dynamic_blocker():
    env = _make_env(5, 1)
    jump = DStarLite(env, 4, 0, allow_jumps=True)
    jump.set_position(0, 0)
    jump.set_dynamic_blockers([(2, 0)])
    jump.plan()
    assert jump._g[jump._start] != _INF, (
        f"jump should pass through dynamic blocker, got g={jump._g[jump._start]}"
    )


def test_jump_endpoint_on_wall_rejected():
    env = _make_env(4, 1, walls=[(3, 0)])
    jump = DStarLite(env, 3, 0, allow_jumps=True)
    jump.set_position(0, 0)
    jump.plan()
    assert jump._g[jump._start] == _INF, (
        f"jump endpoint on wall must be rejected, got g={jump._g[jump._start]}"
    )


def test_walk_only_regression():
    env = _make_env(10, 10)
    walk = DStarLite(env, 9, 0)
    walk.set_position(0, 0)
    walk.plan()
    path = walk.extract_path()
    assert path == [(x, 0) for x in range(10)], (
        f"expected straight walk (0,0)->(9,0), got {path}"
    )
    # step() must still work in walk mode.
    walk2 = DStarLite(env, 5, 5)
    walk2.set_position(0, 0)
    direction = walk2.step()
    assert direction is not None


# -------- Runner --------

TESTS = [
    test_construction_both_modes,
    test_step_raises_in_jump_mode,
    test_step_works_in_walk_mode,
    test_recompute_rhs_jump_enables_reachability,
    test_extract_path_returns_jump_segment,
    test_notify_map_changes_updates_jump_predecessors,
    test_set_dynamic_blockers_updates_jump_predecessors,
    test_walk_preferred_when_cheaper,
    test_jump_passes_through_wall,
    test_jump_passes_through_dynamic_blocker,
    test_jump_endpoint_on_wall_rejected,
    test_walk_only_regression,
]


def main() -> int:
    failed = 0
    for test in TESTS:
        name = test.__name__
        try:
            test()
        except Exception:
            failed += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
        else:
            print(f"PASS  {name}")
    if failed:
        print(f"\n{failed} test(s) failed")
        return 1
    print(f"\nAll {len(TESTS)} test(s) passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
