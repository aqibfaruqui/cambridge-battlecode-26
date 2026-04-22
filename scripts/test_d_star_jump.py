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


# -------- Runner --------

TESTS = [
    test_construction_both_modes,
    test_step_raises_in_jump_mode,
    test_step_works_in_walk_mode,
    test_recompute_rhs_jump_enables_reachability,
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
