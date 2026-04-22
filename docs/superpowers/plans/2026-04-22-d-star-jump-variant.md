# D* Lite Jump Variant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `bots/v11/utils/pathfinding/d_star.py`'s `DStarLite` class with an `allow_jumps` mode so a builder bot can plan a jump-aware route (for bridge placement) alongside its normal walk route, over a shared `EnvironmentMap`.

**Architecture:** Single class with an `allow_jumps: bool` constructor flag. Walk-only code paths (the default) stay bit-identical. Jump mode adds 16 extra "jump" edges per cell (`dist_sq ∈ {5, 8, 9}`) at flat cost 5. Endpoint rules for jumps are identical to walk rules; the path *between* endpoints is ignored. Hot methods branch once on `self._allow_jumps` at the top and run either the walk-only path or walk-plus-jump path.

**Tech Stack:** Python 3.12, existing project deps only. No test framework in the repo — tests are written as a standalone script runnable via `uv run scripts/test_d_star_jump.py`, with assertion-based checks and non-zero exit on failure.

---

## File Structure

- **Modify:** `bots/v11/utils/pathfinding/d_star.py` — add `_JUMP_OFFSETS` constant, two new slots (`_allow_jumps`, `_jump_cost`), two constructor kwargs, and jump-edge handling in `_recompute_rhs`, `extract_path`, `notify_map_changes`, `set_dynamic_blockers`; add `step()` guard.
- **Create:** `scripts/test_d_star_jump.py` — standalone assertion-based test harness, built up task-by-task alongside the implementation (TDD).

## Naming Conventions

Prose and spec code examples use descriptive names (`width`, `height`, `cell_index`, `successor_index`, `jump_cost`, `dynamic_blocked`, `environment_array`, `block_mask`, `neighbour_x`, `neighbour_y`, `candidate_cost`, `successor_g`). The existing hot paths in `d_star.py` use shorter local aliases (`w`, `h`, `u`, `s`, `arr`, `dyn`, `mask`, etc.). When adding new code inside an existing method, follow that method's existing local-alias convention so the surrounding code remains uniform. `dx, dy` stay as-is — they're standard mathematical offsets.

---

## Task 1: Add `_JUMP_OFFSETS` constant, constructor params, and test harness skeleton

**Files:**
- Modify: `bots/v11/utils/pathfinding/d_star.py` (constants block around line 22-49; `DStarLite.__slots__` around lines 52-72; `DStarLite.__init__` around lines 74-108)
- Create: `scripts/test_d_star_jump.py`

### Steps

- [ ] **Step 1: Create the test harness skeleton with the construction test**

Create `scripts/test_d_star_jump.py` with exactly this content:

```python
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
```

- [ ] **Step 2: Run the harness to verify it fails**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `FAIL test_construction_both_modes` with `AttributeError: '_allow_jumps'` or similar — the slot does not yet exist.

- [ ] **Step 3: Add `_JUMP_OFFSETS` constant to `d_star.py`**

In `bots/v11/utils/pathfinding/d_star.py`, directly after the existing `_SEEK_BLOCK_MASK` definition (around line 49), add:

```python
# Jump-edge offsets: (dx, dy) pairs with 2 < dx*dx + dy*dy <= 9.
# Jumps conceptually bypass any tiles between source and destination; the
# endpoint is still validated against block_mask and _dynamic_blocked.
_JUMP_OFFSETS = (
    # dist_sq = 5
    (-2, -1), (-2,  1), ( 2, -1), ( 2,  1),
    (-1, -2), ( 1, -2), (-1,  2), ( 1,  2),
    # dist_sq = 8
    (-2, -2), ( 2, -2), (-2,  2), ( 2,  2),
    # dist_sq = 9
    (-3,  0), ( 3,  0), ( 0, -3), ( 0,  3),
)
```

- [ ] **Step 4: Add the two new slots**

In `DStarLite.__slots__` (around lines 53-72), append `"_allow_jumps"` and `"_jump_cost"` as the final two entries. After the change, the tuple's last three lines should read:

```python
        "_block_mask",
        "_dynamic_blocked",
        "_unknown_cost",
        "_allow_jumps",
        "_jump_cost",
    )
```

- [ ] **Step 5: Add the two new constructor kwargs**

Modify `DStarLite.__init__` (around line 74). The new signature is:

```python
    def __init__(
        self,
        env: EnvironmentMap,
        goal_x: int,
        goal_y: int,
        *,
        block_mask: int = _DEFAULT_BLOCK_MASK,
        unknown_cost: float = 1.0,
        allow_jumps: bool = False,
        jump_cost: float = 5.0,
    ):
```

At the bottom of `__init__`, directly after `self._unknown_cost = unknown_cost` (around line 108), add:

```python
        self._allow_jumps = allow_jumps
        self._jump_cost = jump_cost
```

- [ ] **Step 6: Run the harness to verify it passes**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `PASS test_construction_both_modes` and `All 1 test(s) passed`.

- [ ] **Step 7: Verify walk-only callers still work**

Run: `uv run python -c "import sys; sys.path.insert(0, 'bots/v11'); from utils.pathfinding.d_star import DStarLite; from utils.map.raw_map_representation import EnvironmentMap; env = EnvironmentMap(20, 20); p = DStarLite(env, 10, 10); p.set_position(0, 0); p.plan(); print('ok')"`
Expected: `ok` (no exception — default `allow_jumps=False` path is unchanged).

- [ ] **Step 8: Commit**

```bash
git add bots/v11/utils/pathfinding/d_star.py scripts/test_d_star_jump.py
git commit -m "feat(d_star): add allow_jumps/jump_cost params and _JUMP_OFFSETS constant"
```

---

## Task 2: `step()` raises in jump mode

**Files:**
- Modify: `bots/v11/utils/pathfinding/d_star.py` (`DStarLite.step` around lines 192-231)
- Modify: `scripts/test_d_star_jump.py`

### Steps

- [ ] **Step 1: Add the failing test**

In `scripts/test_d_star_jump.py`, add this function *before* the `TESTS` list:

```python
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
```

Update the `TESTS` list:

```python
TESTS = [
    test_construction_both_modes,
    test_step_raises_in_jump_mode,
    test_step_works_in_walk_mode,
]
```

- [ ] **Step 2: Run to verify the new test fails**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `FAIL test_step_raises_in_jump_mode` with `AssertionError: expected RuntimeError from step() in jump mode`. The other two tests pass.

- [ ] **Step 3: Add the guard to `step()`**

In `bots/v11/utils/pathfinding/d_star.py`, at the very top of `DStarLite.step`, insert the guard as the first two lines of the body:

```python
    def step(self) -> Direction | None:
        if self._allow_jumps:
            raise RuntimeError(
                "step() is undefined when allow_jumps=True; use extract_path()"
            )
        if self._start == self._goal:
            return Direction.CENTRE
        # ... rest of existing body unchanged ...
```

- [ ] **Step 4: Run to verify all tests pass**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `All 3 test(s) passed`.

- [ ] **Step 5: Commit**

```bash
git add bots/v11/utils/pathfinding/d_star.py scripts/test_d_star_jump.py
git commit -m "feat(d_star): step() raises RuntimeError in jump mode"
```

---

## Task 3: `_recompute_rhs` jump-edge block

**Files:**
- Modify: `bots/v11/utils/pathfinding/d_star.py` (`DStarLite._recompute_rhs` around lines 369-528, specifically the point just before the `self._rhs[u] = min_rhs` line ~514)
- Modify: `scripts/test_d_star_jump.py`

### Steps

- [ ] **Step 1: Add the failing test**

Scenario: a 5×3 grid, all traversable except a solid wall column at `x=2`. Walk from `(0, 1)` to `(4, 1)` is impossible. In jump mode, `(0, 1) → (3, 1)` is a valid jump (dx=3, dy=0, dist_sq=9) and `(3, 1)` is traversable — the jump passes through the wall column — then walk to `(4, 1)`.

Add to `scripts/test_d_star_jump.py` before the `TESTS` list:

```python
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
```

Append to `TESTS`:

```python
    test_recompute_rhs_jump_enables_reachability,
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `FAIL test_recompute_rhs_jump_enables_reachability` — the jump planner cannot reach the goal because jump edges are not yet considered. The assertion on `jump._g[jump._start] != _INF` fails.

- [ ] **Step 3: Add the jump block to `_recompute_rhs`**

In `bots/v11/utils/pathfinding/d_star.py`, locate `_recompute_rhs` (around line 369). The existing walk-edge logic ends just before `self._rhs[u] = min_rhs` (around line 514). Insert the jump block there, between the end of the walk relaxation and the `self._rhs[u] = min_rhs` line:

```python
        if self._allow_jumps:
            jc = self._jump_cost
            if 3 <= x < w - 3 and 3 <= y < h - 3:
                for dx, dy in _JUMP_OFFSETS:
                    s = u + dy * w + dx
                    if s != start and (s in dyn or (mask >> arr[s]) & 1):
                        continue
                    gs = g[s]
                    if gs < min_rhs:
                        v = jc + gs
                        if v < min_rhs:
                            min_rhs = v
            else:
                for dx, dy in _JUMP_OFFSETS:
                    xx = x + dx
                    if xx < 0 or xx >= w:
                        continue
                    yy = y + dy
                    if yy < 0 or yy >= h:
                        continue
                    s = yy * w + xx
                    if s != start and (s in dyn or (mask >> arr[s]) & 1):
                        continue
                    gs = g[s]
                    if gs < min_rhs:
                        v = jc + gs
                        if v < min_rhs:
                            min_rhs = v

        self._rhs[u] = min_rhs
```

Notes:
- `jc` is a local alias for `self._jump_cost` — matches the surrounding style (`w`, `h`, `g`, `arr`, etc.).
- `start`, `dyn`, `mask`, `arr`, `g` are already locally aliased earlier in `_recompute_rhs` — reuse them.
- The existing `if g[u] != min_rhs:` enqueue block below is left untouched.

- [ ] **Step 4: Run to verify the test passes**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `All 4 test(s) passed`. In particular, `jump._g[jump._start]` should now be around `5 + 1 = 6` (one jump + one walk step).

- [ ] **Step 5: Commit**

```bash
git add bots/v11/utils/pathfinding/d_star.py scripts/test_d_star_jump.py
git commit -m "feat(d_star): consider jump edges in _recompute_rhs when allow_jumps=True"
```

---

## Task 4: `extract_path()` jump-edge descent

**Files:**
- Modify: `bots/v11/utils/pathfinding/d_star.py` (`DStarLite.extract_path` around lines 252-303, specifically the neighbour-scan loop inside `while cur != goal`)
- Modify: `scripts/test_d_star_jump.py`

### Steps

- [ ] **Step 1: Add the failing test**

Same 5×3 map as Task 3. Now assert that `extract_path()` returns a non-empty path containing at least one jump segment (`max(|dx|, |dy|) > 1`):

```python
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
```

Append to `TESTS`:

```python
    test_extract_path_returns_jump_segment,
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `FAIL test_extract_path_returns_jump_segment`. `extract_path` currently only scans the 8 walk edges; it walks to `(1, 1)` (where `g` is finite) but then fails to descend further because the walk-edge choices don't reach the jump successor. Depending on exact cell g-values, `path` may be empty (greedy descent loops and returns `[]`) or contain only walk steps — either way the `has_jump` assertion fails.

- [ ] **Step 3: Add the jump block to `extract_path`**

In `bots/v11/utils/pathfinding/d_star.py`, locate `extract_path` (around line 252). The neighbour scan that sets `(best, best_cost)` is inside the `while cur != goal` loop (around lines 280-295). After the existing `for dx, dy, cost, _ in _NEIGHBOURS:` loop body finishes (and *before* the `if best is None or best in visited:` check), insert:

```python
            if self._allow_jumps:
                jc = self._jump_cost
                for dx, dy in _JUMP_OFFSETS:
                    xx = x + dx
                    if xx < 0 or xx >= w:
                        continue
                    yy = y + dy
                    if yy < 0 or yy >= h:
                        continue
                    nxt = yy * w + xx
                    if nxt in dyn:
                        continue
                    if (mask >> arr[nxt]) & 1:
                        continue
                    v = jc + g[nxt]
                    if v < best_cost:
                        best_cost = v
                        best = nxt
```

This reuses the same local aliases (`w`, `h`, `g`, `dyn`, `mask`, `arr`) already set earlier in the method.

- [ ] **Step 4: Run to verify the test passes**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `All 5 test(s) passed`. The returned path should look like `[(0, 1), (3, 1), (4, 1)]` (one jump segment then one walk segment), though the exact start-adjacent waypoint may differ depending on tiebreaking — the assertion only checks that *some* segment is a jump.

- [ ] **Step 5: Commit**

```bash
git add bots/v11/utils/pathfinding/d_star.py scripts/test_d_star_jump.py
git commit -m "feat(d_star): extract_path considers jump edges when allow_jumps=True"
```

---

## Task 5: `notify_map_changes` jump predecessors

**Files:**
- Modify: `bots/v11/utils/pathfinding/d_star.py` (`DStarLite.notify_map_changes` around lines 126-168, specifically the per-changed-cell block around lines 144-164)
- Modify: `scripts/test_d_star_jump.py`

### Steps

- [ ] **Step 1: Add the failing test**

Scenario: plan on an open 7×3 map (no walls) in jump mode. The shortest path is all walking. Then add a wall column at `x=2, 3, 4` (all three rows) via `env._array` mutation, call `notify_map_changes`, and re-plan. The new shortest path should contain a jump (since the only way across the wall column is a jump).

```python
def test_notify_map_changes_updates_jump_predecessors():
    width, height = 7, 3
    env = _make_env(width, height)

    jump = DStarLite(env, 6, 1, allow_jumps=True)
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

    # Drop in a wall column across x=2, 3, 4.
    for x in (2, 3, 4):
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
```

Append to `TESTS`:

```python
    test_notify_map_changes_updates_jump_predecessors,
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `FAIL test_notify_map_changes_updates_jump_predecessors` — without the jump-predecessor propagation, `notify_map_changes` only recomputes walk predecessors of the changed cells, so jump edges landing *on* the new walls never get recomputed and stale g-values linger. The post-change `extract_path()` may return a broken path or miss the jump detour.

- [ ] **Step 3: Add the jump-predecessor loop**

In `bots/v11/utils/pathfinding/d_star.py`, locate `notify_map_changes` (around line 126). Inside the per-changed-cell block (after the existing walk-predecessor propagation, which ends with `recompute(i + 1)` at ~line 162 and before the unconditional `recompute(i)` at ~line 164), insert the jump-predecessor block:

```python
                if x > 0:
                    recompute(i - 1)
                if x < w - 1:
                    recompute(i + 1)

                if self._allow_jumps:
                    for dx, dy in _JUMP_OFFSETS:
                        xx = x + dx
                        if xx < 0 or xx >= w:
                            continue
                        yy = y + dy
                        if yy < 0 or yy >= h:
                            continue
                        recompute(yy * w + xx)

                recompute(i)
            i += 1
```

The self-recompute `recompute(i)` still runs last, unchanged.

- [ ] **Step 4: Run to verify the test passes**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `All 6 test(s) passed`. The post-insertion `path_after` should include a jump across the new wall column.

- [ ] **Step 5: Commit**

```bash
git add bots/v11/utils/pathfinding/d_star.py scripts/test_d_star_jump.py
git commit -m "feat(d_star): notify_map_changes recomputes jump predecessors when allow_jumps=True"
```

---

## Task 6: `set_dynamic_blockers` jump predecessors

**Files:**
- Modify: `bots/v11/utils/pathfinding/d_star.py` (`DStarLite.set_dynamic_blockers` around lines 170-190)
- Modify: `scripts/test_d_star_jump.py`

### Steps

- [ ] **Step 1: Add the failing test**

Scenario: same 5×3 map as Task 3 (walls at `x=2`, start `(0,1)`, goal `(4,1)`). Plan the jump path — it exists, uses a jump. Now add a dynamic blocker at `(3, 1)` (the jump landing cell). The plan should degrade — depending on the other jump endpoints available around `x=3`, the path may re-route via another jump endpoint. The simplest assertion: after blocking *every* traversable cell at `x=3`, the goal becomes unreachable (`g[start] == _INF`).

```python
def test_set_dynamic_blockers_updates_jump_predecessors():
    width, height = 5, 3
    walls = [(2, y) for y in range(height)]
    env = _make_env(width, height, walls=walls)

    jump = DStarLite(env, 4, 1, allow_jumps=True)
    jump.set_position(0, 1)
    jump.plan()
    assert jump._g[jump._start] != _INF, "baseline jump route should exist"

    # Block every cell at x=3 as dynamic blockers. The only cells at x=4 are
    # (4,0), (4,1)=goal, (4,2). Jumps from (0,1) or (1,*) to (4,*) have
    # dist_sq >= 10 (out of reach). Jumps to (3,*) are all blocked. Walk is
    # still blocked by the wall column at x=2.
    jump.set_dynamic_blockers([(3, 0), (3, 1), (3, 2)])

    assert jump._g[jump._start] == _INF, (
        f"blocking all x=3 cells should make goal unreachable, got g={jump._g[jump._start]}"
    )
```

Append to `TESTS`:

```python
    test_set_dynamic_blockers_updates_jump_predecessors,
```

Note: the plan also needs to consider jumps landing directly at `(4, 0)` and `(4, 2)`. From `(0, 1)`, the closest-to-x=4 jumps are `(3, 0)` (lands `(3, 1)`) — already blocked — so this needs checking. Let me enumerate jumps from cells the walker can reach (`(0, 1)` and its walk neighbours `(0, 0)`, `(0, 2)`, `(1, 0)`, `(1, 1)`, `(1, 2)`):

- From `(1, 1)`: `(3, 0)` lands `(4, 1)` — this is the goal at x=4! dist_sq = 9. ✓ Valid. **This jump bypasses the x=3 dynamic blockers.**

So the test as written is wrong. Revise it to also block cells reachable by a direct-to-goal-row jump. Rework:

```python
def test_set_dynamic_blockers_updates_jump_predecessors():
    width, height = 5, 3
    walls = [(2, y) for y in range(height)]
    env = _make_env(width, height, walls=walls)

    jump = DStarLite(env, 4, 1, allow_jumps=True)
    jump.set_position(0, 1)
    jump.plan()
    assert jump._g[jump._start] != _INF, "baseline jump route should exist"

    # Block the goal (4,1) itself as a dynamic blocker — a jump endpoint on
    # a dynamic blocker must be rejected, so every edge into the goal dies
    # and g[start] becomes infinity.
    jump.set_dynamic_blockers([(4, 1)])

    assert jump._g[jump._start] == _INF, (
        f"blocking goal endpoint should make it unreachable, got g={jump._g[jump._start]}"
    )
```

Use this simpler assertion.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `FAIL test_set_dynamic_blockers_updates_jump_predecessors` — without the jump-predecessor propagation in `set_dynamic_blockers`, cells that have jump edges landing at `(4, 1)` do not get their `rhs` recomputed, so stale g-values from before the blocker persist.

- [ ] **Step 3: Add the jump-predecessor loop**

In `bots/v11/utils/pathfinding/d_star.py`, locate `set_dynamic_blockers` (around line 170). Inside the `for idx in changed_nodes:` loop (lines 182-185), after the existing `for pred in self._pred(idx): self._recompute_rhs(pred)` walk-predecessor loop, add the jump-predecessor block. The full loop becomes:

```python
        for idx in changed_nodes:
            self._recompute_rhs(idx)
            for pred in self._pred(idx):
                self._recompute_rhs(pred)
            if self._allow_jumps:
                x = idx % self._w
                y = idx // self._w
                for dx, dy in _JUMP_OFFSETS:
                    xx = x + dx
                    if xx < 0 or xx >= self._w:
                        continue
                    yy = y + dy
                    if yy < 0 or yy >= self._h:
                        continue
                    self._recompute_rhs(yy * self._w + xx)
```

- [ ] **Step 4: Run to verify the test passes**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `All 7 test(s) passed`.

- [ ] **Step 5: Commit**

```bash
git add bots/v11/utils/pathfinding/d_star.py scripts/test_d_star_jump.py
git commit -m "feat(d_star): set_dynamic_blockers recomputes jump predecessors when allow_jumps=True"
```

---

## Task 7: Cost preference and pass-through scenario tests

**Files:**
- Modify: `scripts/test_d_star_jump.py` (tests only — no production code changes)

### Steps

- [ ] **Step 1: Add the cost-preference test**

On an open map with no obstructions, the jump planner must still prefer walking when walking is cheaper. Walking `(0, 0) → (3, 0)` costs 3; a direct `(3, 0)` jump costs 5. Append to `scripts/test_d_star_jump.py` before the `TESTS` list:

```python
def test_walk_preferred_when_cheaper():
    env = _make_env(10, 10)
    jump = DStarLite(env, 3, 0, allow_jumps=True)
    jump.set_position(0, 0)
    jump.plan()
    path = jump.extract_path()
    assert path == [(0, 0), (1, 0), (2, 0), (3, 0)], (
        f"expected all-walk path on open map, got {path}"
    )
```

- [ ] **Step 2: Add the pass-through-wall test**

A single wall between start and goal. The jump must pass through the wall tile (the intervening cell is a wall). Endpoint is a traversable goal.

```python
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
```

- [ ] **Step 3: Add the pass-through-dynamic-blocker test**

Same 5×1 map but the "obstacle" is a dynamic blocker, not a wall. Jump must still pass through.

```python
def test_jump_passes_through_dynamic_blocker():
    env = _make_env(5, 1)
    jump = DStarLite(env, 4, 0, allow_jumps=True)
    jump.set_position(0, 0)
    jump.set_dynamic_blockers([(2, 0)])
    jump.plan()
    assert jump._g[jump._start] != _INF, (
        f"jump should pass through dynamic blocker, got g={jump._g[jump._start]}"
    )
```

- [ ] **Step 4: Add the endpoint-on-wall rejection test**

A jump must not be allowed to land on a wall tile. Construct a 4×1 map where the goal itself is walled off — the only dist_sq≤9 jump into the goal would land on the wall and must be rejected. Walking is also blocked for the same reason. Result: `g[start] == INF`.

```python
def test_jump_endpoint_on_wall_rejected():
    env = _make_env(4, 1, walls=[(3, 0)])
    jump = DStarLite(env, 3, 0, allow_jumps=True)
    jump.set_position(0, 0)
    jump.plan()
    assert jump._g[jump._start] == _INF, (
        f"jump endpoint on wall must be rejected, got g={jump._g[jump._start]}"
    )
```

- [ ] **Step 5: Add all four to `TESTS`**

```python
    test_walk_preferred_when_cheaper,
    test_jump_passes_through_wall,
    test_jump_passes_through_dynamic_blocker,
    test_jump_endpoint_on_wall_rejected,
```

- [ ] **Step 6: Run to verify all tests pass**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `All 11 test(s) passed`.

Note: these tests should pass with the implementation from Tasks 1-6 already in place — no production code changes are needed. If a test fails, diagnose whether the failure reveals a genuine bug (in which case fix the production code and add a task) or a bad test assumption.

- [ ] **Step 7: Commit**

```bash
git add scripts/test_d_star_jump.py
git commit -m "test(d_star): add cost-preference, pass-through, and endpoint-rejection scenarios"
```

---

## Task 8: Walk-only regression smoke test

**Files:**
- Modify: `scripts/test_d_star_jump.py`

### Steps

- [ ] **Step 1: Add a walk-only regression test**

This exercises the default `allow_jumps=False` path end-to-end to catch any accidental regression. It asserts that on an open map the walk planner returns a straight path of the expected length.

Append to `scripts/test_d_star_jump.py` before the `TESTS` list:

```python
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
```

Append to `TESTS`:

```python
    test_walk_only_regression,
```

- [ ] **Step 2: Run to verify**

Run: `uv run scripts/test_d_star_jump.py`
Expected: `All 12 test(s) passed`.

- [ ] **Step 3: Run a real match with existing bots to catch integration regressions**

Existing callers (harvester seek, harvester return, attacker) use walk-only planners. Run a full v11-vs-v11 match and confirm no crashes or runtime errors originating from `d_star.py`.

Run: `uv run cambc run v11 v11 maps/separated.bin --replay /tmp/d_star_jump_smoke.replay 2>&1 | tail -40`

(If the exact map path / cambc invocation differs, use the canonical form from `CLAUDE.md`'s Quickstart: `cambc run bot1 bot2 <map path> --replay <replay path>`.)

Expected: the match runs to completion with no `RuntimeError`, `AttributeError`, `IndexError`, or other exceptions referencing `d_star.py` in the output. Winner announcement or round-limit termination is fine.

- [ ] **Step 4: Commit**

```bash
git add scripts/test_d_star_jump.py
git commit -m "test(d_star): add walk-only regression assertions"
```

---

## Self-Review Checklist

Before marking the feature done, verify:

- [ ] All 12 tests pass via `uv run scripts/test_d_star_jump.py`.
- [ ] A v11-vs-v11 match runs without `d_star.py`-related errors (Task 8 Step 3).
- [ ] `grep -n "allow_jumps\|_jump_cost\|_JUMP_OFFSETS" bots/v11/utils/pathfinding/d_star.py` shows references in: module constants, `__slots__`, `__init__` signature + body, `step`, `_recompute_rhs`, `extract_path`, `notify_map_changes`, `set_dynamic_blockers`. No other locations should reference these identifiers.
- [ ] Diff summary: only `bots/v11/utils/pathfinding/d_star.py` and `scripts/test_d_star_jump.py` are modified/created. No other files touched.
- [ ] Default-mode (`allow_jumps=False`) behaviour is unchanged for all other callers (harvester seek, harvester return, attacker). Confirmed by match smoke test.
