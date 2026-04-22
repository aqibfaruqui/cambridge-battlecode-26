# Harvester Jump-Bridge Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the harvester's walk-only return planner with a jump-enabled planner that identifies where a long-range resource bridge is more efficient than a conveyor chain routed around a wall; when such a jump is selected, the harvester builds the bridge at launch `A` and physically walks around the obstacle to landing `B` before resuming its normal conveyor-building flow.

**Architecture:** Single file of changes in `bots/v11/utils/harvester_states/return_to_core.py` plus a handful of init-field changes in `bots/v11/builders/harvester.py`. The jump planner replaces `self.return_planner`. A temporary walk-only planner is constructed per jump segment to route the harvester around the obstacle. A persistent per-harvester blacklist prevents the jump planner from retrying landings that turned out to be unreachable.

**Tech Stack:** Python 3.12, existing `DStarLite` class from `utils/pathfinding/d_star.py` (already has `allow_jumps` parameter), existing game bindings from `cambc`. No new dependencies.

---

## Project Orientation (for the engineer)

- **Repo root:** `/Users/alex/projects/cambridge-battlecode-26`.
- **Branch:** `bridging-v2` (already checked out). Do NOT `git checkout <sha>`, `git reset`, `git rebase`, or any history-modifying command — previous implementers got bitten by this. Only use `git status`, `git diff`, `git log`, `git rev-parse HEAD`, `git add <files>`, `git commit`.
- **Key files:**
  - `bots/v11/builders/harvester.py` — the `Harvester` class; `__init__` lives at lines 66-123.
  - `bots/v11/utils/harvester_states/return_to_core.py` — the return-to-core state flow; 448 lines; all helpers are module-level functions that take `self: Harvester, c: Controller` and operate on harvester fields.
  - `bots/v11/utils/pathfinding/d_star.py` — the `DStarLite` class. It supports `allow_jumps: bool = False` and `jump_cost: float = 5.0` kwargs. When `allow_jumps=True`, `step()` raises `RuntimeError` — callers must use `extract_path()` and derive a direction from the first two waypoints.
  - `bots/v11/builders/attacker.py` — for reference; shows the "build a road before moving" idiom used during walk-around.
  - `bots/v11/utils/pathfinding/movement.py` — helpers like `DIRECTIONS_4` (the cardinal-directions tuple).
- **Testing conventions:** this project has NO unit-test scaffold for harvester flows. Validation is via full `cambc run` matches. Do NOT add pytest, unittest, or any test framework; don't invent tests for functions that have no harness. Each task's verification step is a syntax/import check; the final task runs an actual match.
- **Commit rule:** the user rejects `Co-Authored-By:` trailers — NEVER add them.
- **Spec:** `docs/superpowers/specs/2026-04-22-harvester-jump-integration-design.md`.

---

## File Structure

Only two files are modified:

- **`bots/v11/builders/harvester.py`** — Harvester class init; remove `self.return_planner`, add 4 new fields.
- **`bots/v11/utils/harvester_states/return_to_core.py`** — rename two helpers, rewire them for the jump planner, add two new helpers, and extend `_build_return_step` with two new dispatch gates.

No new files.

---

## Task 1: Add new Harvester fields

Introduce the four new jump-state fields on the Harvester class. Leave the old `return_planner` field intact in this task so subsequent helper changes can be staged safely. The field removal happens atomically with the helper rewire in Task 4.

**Files:**
- Modify: `bots/v11/builders/harvester.py` (`Harvester.__init__`, around line 84)
- Modify: `bots/v11/utils/harvester_states/return_to_core.py` (`_reset_return_state`, around line 38)

### Steps

- [ ] **Step 1: Add the four new fields in `Harvester.__init__`**

In `bots/v11/builders/harvester.py`, find the line `self.return_planner: DStarLite | None = None` (around line 84). Immediately after it, add:

```python
        self.return_jump_planner: DStarLite | None = None
        self.return_jump_blacklist: set[tuple[int, int]] = set()
        self.return_jump_walker: DStarLite | None = None
        self.return_jump_landing: tuple[int, int] | None = None
```

Do not remove `self.return_planner` yet — Task 4 does that.

- [ ] **Step 2: Extend `_reset_return_state` to clear the new transient fields**

In `bots/v11/utils/harvester_states/return_to_core.py`, find `_reset_return_state` (around line 38). Its full body is currently:

```python
def _reset_return_state(self: Harvester):
    self.bridge_from = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}
```

Add two new clearing lines at the end (the blacklist is NOT reset):

```python
def _reset_return_state(self: Harvester):
    self.bridge_from = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}
    self.return_jump_walker = None
    self.return_jump_landing = None
```

The `return_jump_planner` field is intentionally NOT cleared here — Task 4 adds that line when the old `return_planner` is removed.

- [ ] **Step 3: Verify via import check**

Run: `uv run python -c "import sys; sys.path.insert(0, 'bots/v11'); from builders.harvester import Harvester; from utils.harvester_states.return_to_core import _reset_return_state; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add bots/v11/builders/harvester.py bots/v11/utils/harvester_states/return_to_core.py
git commit -m "feat(harvester): add jump-state fields to Harvester init"
```

Do NOT include a Co-Authored-By trailer.

---

## Task 2: Add `_blacklist_landing` helper

Add the helper that marks a jump landing as permanently unusable for this harvester, clearing any in-flight traversal state. Not wired yet.

**Files:**
- Modify: `bots/v11/utils/harvester_states/return_to_core.py` (add new function)

### Steps

- [ ] **Step 1: Add the helper**

In `bots/v11/utils/harvester_states/return_to_core.py`, after the existing `_return_dynamic_blockers` helper (around line 77) and before `_ensure_return_planner`, add:

```python
def _blacklist_landing(self: Harvester, landing_xy: tuple[int, int]) -> None:
    """Permanently mark a jump landing as unreachable for this harvester.
    Clears any in-flight traversal state. The next _ensure_return_jump_planner
    call propagates the blacklist into the jump planner's dynamic blockers."""
    self.return_jump_blacklist.add(landing_xy)
    self.return_jump_walker = None
    self.return_jump_landing = None
```

- [ ] **Step 2: Verify via import check**

Run: `uv run python -c "import sys; sys.path.insert(0, 'bots/v11'); from utils.harvester_states.return_to_core import _blacklist_landing; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add bots/v11/utils/harvester_states/return_to_core.py
git commit -m "feat(harvester): add _blacklist_landing helper"
```

Do NOT include a Co-Authored-By trailer.

---

## Task 3: Add `_start_or_continue_jump` helper

Add the state machine that handles a jump segment: first turn builds the bridge and constructs the walker; subsequent turns step the walker around the obstacle until the harvester arrives at the landing. Not wired yet.

**Files:**
- Modify: `bots/v11/utils/harvester_states/return_to_core.py` (add new function)

### Steps

- [ ] **Step 1: Add the helper**

In `bots/v11/utils/harvester_states/return_to_core.py`, after `_blacklist_landing` (added in Task 2) and before `_ensure_return_planner`, add:

```python
def _start_or_continue_jump(
    self: Harvester,
    c: Controller,
    landing_xy: tuple[int, int],
) -> bool:
    """Bridge build + walk-around traversal for a single jump segment.

    First call with no walker set: pre-validates walk-around reachability,
    builds the long-range resource bridge, constructs a temp walk-only
    planner targeting B. Subsequent calls step the walker one cell at a
    time with road-paving (no conveyors, no corner-cut bridges). Returns
    True if the turn was consumed.
    """
    if self.return_jump_walker is None:
        A = self.current_pos
        B = Position(landing_xy[0], landing_xy[1])

        if self.environment_map is None:
            return False

        probe = DStarLite(
            self.environment_map, B.x, B.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
        )
        probe.set_dynamic_blockers(_return_dynamic_blockers(c))
        probe.set_position(A.x, A.y)
        probe.plan()
        if len(probe.extract_path()) < 2:
            _blacklist_landing(self, landing_xy)
            return False

        if not c.can_build_bridge(A, B):
            ti, _ = c.get_global_resources()
            bridge_cost_ti, _ = c.get_bridge_cost()
            if ti < bridge_cost_ti:
                return False
            _blacklist_landing(self, landing_xy)
            return False

        c.build_bridge(A, B)
        self.return_jump_walker = probe
        self.return_jump_landing = landing_xy
        return True

    walker = self.return_jump_walker
    walker.set_dynamic_blockers(_return_dynamic_blockers(c))
    walker.notify_map_changes()
    walker.set_position(self.current_pos.x, self.current_pos.y)

    path = walker.extract_path()
    if len(path) < 2:
        _blacklist_landing(self, landing_xy)
        return False

    nxt = path[1]
    move_dir = self.current_pos.direction_to(Position(nxt[0], nxt[1]))
    if move_dir is None:
        return False

    next_pos = self.current_pos.add(move_dir)
    if c.get_action_cooldown() == 0 and c.can_build_road(next_pos):
        c.build_road(next_pos)

    if not c.can_move(move_dir):
        return False
    c.move(move_dir)

    if (self.current_pos.x, self.current_pos.y) == landing_xy:
        self.return_jump_walker = None
        self.return_jump_landing = None

    return True
```

- [ ] **Step 2: Verify via import check**

Run: `uv run python -c "import sys; sys.path.insert(0, 'bots/v11'); from utils.harvester_states.return_to_core import _start_or_continue_jump; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add bots/v11/utils/harvester_states/return_to_core.py
git commit -m "feat(harvester): add _start_or_continue_jump state machine"
```

Do NOT include a Co-Authored-By trailer.

---

## Task 4: Rewire the planner and dispatcher

Atomic refactor: swap `self.return_planner` → `self.return_jump_planner` (with `allow_jumps=True`), replace `_planner_step_at` with `_planner_direction_at` (uses `extract_path` since jump-mode `step()` raises), and add the two new dispatch gates to `_build_return_step`. After this task the jump-bridge feature is fully live.

**Files:**
- Modify: `bots/v11/builders/harvester.py` (remove `self.return_planner` line)
- Modify: `bots/v11/utils/harvester_states/return_to_core.py` (rename helpers, rewire callers, extend `_build_return_step`, update `_reset_return_state`)

### Steps

- [ ] **Step 1: Remove the old `return_planner` field**

In `bots/v11/builders/harvester.py`, delete this line (around line 84):

```python
        self.return_planner: DStarLite | None = None
```

The four new jump-state fields added in Task 1 remain.

- [ ] **Step 2: Update `_reset_return_state` to clear `return_jump_planner`**

In `bots/v11/utils/harvester_states/return_to_core.py`, find `_reset_return_state`. Replace the line `self.return_planner = None` with `self.return_jump_planner = None`. After this step the full body reads:

```python
def _reset_return_state(self: Harvester):
    self.bridge_from = None
    self.return_next_dir = None
    self.return_jump_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}
    self.return_jump_walker = None
    self.return_jump_landing = None
```

- [ ] **Step 3: Rename `_ensure_return_planner` and switch to the jump planner**

In `bots/v11/utils/harvester_states/return_to_core.py`, replace the entire existing `_ensure_return_planner` function (around lines 80-93) with:

```python
def _ensure_return_jump_planner(self: Harvester, c: Controller):
    if self.return_jump_planner is None and self.environment_map is not None:
        self.return_jump_planner = DStarLite(
            self.environment_map,
            self.core_pos.x,
            self.core_pos.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
            allow_jumps=True,
        )
    p = self.return_jump_planner
    if p is not None:
        blockers = _return_dynamic_blockers(c) + list(self.return_jump_blacklist)
        p.set_dynamic_blockers(blockers)
        p.notify_map_changes()
    return p
```

Changes vs. the original: return field is `return_jump_planner`, `allow_jumps=True` is passed, and `set_dynamic_blockers` receives the union of current-turn blockers and the persistent blacklist.

- [ ] **Step 4: Replace `_planner_step_at` with `_planner_direction_at`**

Still in `return_to_core.py`, replace the entire existing `_planner_step_at` function (around lines 96-102) with:

```python
def _planner_direction_at(self: Harvester, c: Controller, pos: Position) -> Direction | None:
    """Return the walk-direction the jump planner would take from `pos`.
    Returns None if there is no path, the next step is a jump (non-adjacent
    waypoint), or the planner is unavailable. Callers treat None as
    "fall back to direction_to(core_pos)"."""
    p = _ensure_return_jump_planner(self, c)
    if p is None:
        return None
    p.set_position(pos.x, pos.y)
    path = p.extract_path()
    if len(path) < 2:
        return None
    x0, y0 = path[0]
    x1, y1 = path[1]
    if max(abs(x1 - x0), abs(y1 - y0)) > 1:
        return None
    return Position(x0, y0).direction_to(Position(x1, y1))
```

- [ ] **Step 5: Update all callers of `_planner_step_at`**

There are three call sites inside `return_to_core.py`. The signatures are identical, the return-value contract is the same (`Direction | None` with `None` meaning "fall back"). Rename each call site:

Around line 191, inside `_next_dir_after_move`:
```python
# before
        follow_dir = _planner_step_at(self, c, move_pos)
# after
        follow_dir = _planner_direction_at(self, c, move_pos)
```

Around line 277, inside `_handle_bridge_state`'s post-bridge-conveyor block:
```python
# before
        conveyor_dir = _planner_step_at(self, c, self.current_pos)
# after
        conveyor_dir = _planner_direction_at(self, c, self.current_pos)
```

Around line 329, inside `_build_return_step`'s `just_placed` block:
```python
# before
        step = _planner_step_at(self, c, move_pos) or move_pos.direction_to(self.core_pos)
# after
        step = _planner_direction_at(self, c, move_pos) or move_pos.direction_to(self.core_pos)
```

After this step, `_planner_step_at` is not referenced anywhere. `grep -n "_planner_step_at" bots/v11/utils/harvester_states/return_to_core.py` must return nothing.

- [ ] **Step 6: Rewire the main `_build_return_step` planner call**

In `_build_return_step` (around line 356), the current code is:

```python
    planner = _ensure_return_planner(self, c)
    planner_step: Direction | None = None
    planner_path: list[tuple[int, int]] = []
    if planner is not None:
        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner_step = planner.step()
        planner_path = planner.extract_path()
```

Replace with the jump-planner-aware form (derives direction from the first path segment, detects jump segments, and sets `planner_step` to None for jump segments so the existing `None`→`direction_to(core_pos)` fallback fires — but only when there is no gate-6b dispatch):

```python
    planner = _ensure_return_jump_planner(self, c)
    planner_step: Direction | None = None
    planner_path: list[tuple[int, int]] = []
    first_segment_is_jump = False
    if planner is not None:
        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner_path = planner.extract_path()
        if len(planner_path) >= 2:
            x0, y0 = planner_path[0]
            x1, y1 = planner_path[1]
            if max(abs(x1 - x0), abs(y1 - y0)) > 1:
                first_segment_is_jump = True
            else:
                planner_step = Position(x0, y0).direction_to(Position(x1, y1))

    if first_segment_is_jump and self.return_next_dir is None:
        return _start_or_continue_jump(self, c, planner_path[1])
```

Note: if `self.return_next_dir` is set (carry-forward from a previous diagonal split), we honour it and defer the jump to the next turn — that matches the existing "stashed direction takes precedence" invariant.

- [ ] **Step 7: Add gate 1 (walker-active check) at the top of `_build_return_step`**

In `_build_return_step`, insert a new block at the very top of the function body (before the `if self.just_placed:` block). The top of the function should read:

```python
def _build_return_step(self: Harvester, c: Controller) -> bool:
    if self.return_jump_walker is not None:
        assert self.return_jump_landing is not None
        return _start_or_continue_jump(self, c, self.return_jump_landing)

    # On the first turn after placing a harvester, place a connector conveyor on
    # the starting tile (choosing the closer cardinal join tile when the placement
    # was diagonal) so the chain begins before the normal walk-back loop takes over.
    if self.just_placed:
        # ... existing body unchanged ...
```

After this step, mid-traversal turns are entirely handled by `_start_or_continue_jump` and the rest of `_build_return_step` is bypassed.

- [ ] **Step 8: Verify via import + compile check**

Run: `uv run python -c "import sys; sys.path.insert(0, 'bots/v11'); from builders.harvester import Harvester; from utils.harvester_states import return_to_core; print('ok')"`
Expected: `ok`.

Also run: `uv run python -m py_compile bots/v11/utils/harvester_states/return_to_core.py bots/v11/builders/harvester.py && echo compile-ok`
Expected: `compile-ok` (no syntax errors).

Also confirm no references to the old names remain:
```
grep -n "_planner_step_at\|_ensure_return_planner\|self\.return_planner\b" bots/v11/builders/harvester.py bots/v11/utils/harvester_states/return_to_core.py
```
Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add bots/v11/builders/harvester.py bots/v11/utils/harvester_states/return_to_core.py
git commit -m "feat(harvester): use jump-enabled planner with bridge+walk-around for return"
```

Do NOT include a Co-Authored-By trailer.

---

## Task 5: Match smoke validation

Run a full v11-vs-v11 match and verify the harvester return flow doesn't regress and — when the map has obstructions between deploy points and core — builds long-range bridges.

**Files:** no file changes.

### Steps

- [ ] **Step 1: Smoke match (clean-play regression)**

Run: `uv run cambc run v11 v11 arena.map26 --replay /tmp/harvester_jump_smoke.replay --seed 1 2>&1 | tail -50`

If the map `arena.map26` isn't recognized, try alternatives from the repo (e.g. `separated`, `default_large1`). Use whatever map the previous smoke run in this session used.

**Pass criteria:**
- The match runs to completion (winner announcement or round-limit termination).
- No `Traceback`, `RuntimeError`, `AttributeError`, `KeyError`, or other exception strings mentioning `return_to_core.py` or `harvester.py` in the output.
- Both harvesters place harvesters and return resources during the match (look for Titanium > 0 in the final score summary).

If any of these fail, the task is BLOCKED — report exactly what went wrong (paste the relevant output) instead of trying to patch the implementation.

- [ ] **Step 2: Replay spot-check for jump behaviour (optional visual)**

Open `/tmp/harvester_jump_smoke.replay` in whatever tool the user normally uses to view replays. Confirm:
- Long-range bridges are placed when the harvester encounters a wall between itself and core.
- The harvester physically walks around the bridged obstacle rather than attempting to cross.
- Conveyor chain continues at the bridge's landing side.

If no such wall arises in this match (the default maps may not exercise the path), skip this step and note it in the report.

- [ ] **Step 3: Commit nothing; the task is validation-only**

If both prior steps pass, there's nothing to commit for this task. If a real bug surfaces in steps 1-2, file it as a new task (don't bundle a fix with the smoke validation).

---

## Self-Review Checklist

Before declaring the plan complete:

- [ ] All 5 tasks implemented and committed.
- [ ] `grep -n "_planner_step_at\|_ensure_return_planner\|self\.return_planner\b" bots/v11/` returns nothing (old names fully gone).
- [ ] Smoke match passes with no tracebacks.
- [ ] Diff summary: only `bots/v11/builders/harvester.py` and `bots/v11/utils/harvester_states/return_to_core.py` modified.
- [ ] No `Co-Authored-By:` trailers in any commit from this plan.
