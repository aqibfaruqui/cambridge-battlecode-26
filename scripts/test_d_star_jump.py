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


# -------- Runner --------

TESTS = [
    test_construction_both_modes,
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
