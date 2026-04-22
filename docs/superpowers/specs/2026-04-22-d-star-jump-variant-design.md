# D* Lite Jump Variant — Design

**Date:** 2026-04-22
**File to modify:** `bots/v11/utils/pathfinding/d_star.py`

## Problem

A builder bot needs two route plans over the same `EnvironmentMap`, from the same start to the same goal:

1. A **walk route** — the 8-connected path the bot will physically follow.
2. A **jump route** — a plan that can also take "jump" edges representing future bridge placements. Jumps conceptually pass through walls, ore, enemy core, unknown, and dynamic blockers between source and destination, but still require a traversable endpoint.

The walk route drives stepping. The jump route is an advisor: its waypoints tell the builder where bridges should go. Both plans live on a single bot, so they share the same environment map but maintain independent search state.

## Scope

Extend the existing `DStarLite` class in-place so it can be instantiated in either walk-only or jump-enabled mode. The builder holds two instances, one of each mode, over a shared `EnvironmentMap`. All other callers (harvester seek, harvester return, attacker) keep using the default walk-only mode with zero behavioural change.

Non-goals:
- Throttling or frequency decisions (left to the call site).
- A new pathfinding algorithm — this is an edge-set extension of D* Lite.
- Inheritance or subclassing — we keep one class with a flag.

## Public API

```python
DStarLite(
    env, goal_x, goal_y,
    *,
    block_mask=_DEFAULT_BLOCK_MASK,
    unknown_cost=1.0,
    allow_jumps=False,    # new
    jump_cost=5.0,        # new
)
```

Two new `__slots__`: `_allow_jumps`, `_jump_cost`.

- **Walk mode** (`allow_jumps=False`, default): behaviour is bit-identical to today.
- **Jump mode** (`allow_jumps=True`): `step()` raises `RuntimeError("step() is undefined when allow_jumps=True; use extract_path()")` — `Direction` cannot express a jump. All other public methods (`set_goal`, `set_position`, `plan`, `extract_path`, `extract_path_lines`, `notify_map_changes`, `set_dynamic_blockers`) work in both modes.

Path consumption in jump mode: `extract_path()` returns the existing `list[tuple[int, int]]`. A segment between consecutive points is a jump iff `max(|dx|, |dy|) > 1`. No new data type.

## Jump edge set

Sixteen `(dx, dy)` offsets, module-level constant. All share flat cost `jump_cost` (default 5.0):

```python
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

Rationale for the set:
- `dist_sq ≤ 2` is the existing walk set.
- `dist_sq = 4` offsets (`(±2, 0)`, `(0, ±2)`) are deliberately excluded — a jump across a single orthogonally-adjacent gap is not modelled. The planner routes around via a `(2, ±1)` / `(±1, 2)` jump instead.
- Max reach is `±3`, so the interior fast path in `_recompute_rhs` must require `3 ≤ x < width − 3 and 3 ≤ y < height − 3`.

Symmetry: every offset's negative is also in the set, so predecessor = successor just like the walk set.

## Endpoint and path semantics

- **Jump endpoint rules** are identical to walk endpoint rules: the destination cell must not be in `_dynamic_blocked` and must pass `block_mask`. In particular, `unknown` / wall / ore / enemy core are endpoint-rejected whenever the active mask says so.
- **Path between endpoints** is ignored — any cell type between source and destination is permitted, including dynamic blockers. No ray-casting or line-of-sight check.
- `unknown_cost` is applied only to walk edges (as today). Jumps cost a flat `jump_cost` regardless of endpoint terrain or anything along the way.
- `_km` and `_calc_key` are unchanged. The octile heuristic remains admissible and consistent because the smallest jump has octile distance `≈ 2.41` and every jump costs 5, so for any jump edge from a source cell to a successor cell, `h(source) − h(successor) ≤ octile(source, successor) ≤ 3 ≤ 5 = jump_cost`.

## Method-by-method changes

Each hot method branches once on `self._allow_jumps` at the top level. The walk-only code paths are preserved verbatim. The snippets below use descriptive local names; the existing walk code uses shorter aliases (`w`, `h`, `u`, `s`, `arr`, `dyn`, etc.) for hot-path terseness — the implementation may keep those aliases or expand them at its discretion.

### `_recompute_rhs(cell_index)`

After the existing walk-edge relaxation produces `min_rhs`, if `_allow_jumps` is set, scan jump edges as an additive block:

```python
if self._allow_jumps:
    jump_cost = self._jump_cost
    if 3 <= x < width - 3 and 3 <= y < height - 3:
        # Interior fast path — every offset lands in bounds.
        for dx, dy in _JUMP_OFFSETS:
            successor_index = cell_index + dy * width + dx
            if successor_index != start and (
                successor_index in dynamic_blocked
                or (block_mask >> environment_array[successor_index]) & 1
            ):
                continue
            successor_g = g[successor_index]
            if successor_g < min_rhs:
                candidate_cost = jump_cost + successor_g
                if candidate_cost < min_rhs:
                    min_rhs = candidate_cost
    else:
        # Border — per-offset bounds checks.
        for dx, dy in _JUMP_OFFSETS:
            neighbour_x = x + dx
            if neighbour_x < 0 or neighbour_x >= width:
                continue
            neighbour_y = y + dy
            if neighbour_y < 0 or neighbour_y >= height:
                continue
            successor_index = neighbour_y * width + neighbour_x
            if successor_index != start and (
                successor_index in dynamic_blocked
                or (block_mask >> environment_array[successor_index]) & 1
            ):
                continue
            successor_g = g[successor_index]
            if successor_g < min_rhs:
                candidate_cost = jump_cost + successor_g
                if candidate_cost < min_rhs:
                    min_rhs = candidate_cost
```

The `successor_g < min_rhs` early prune remains valid: `candidate_cost = jump_cost + successor_g`, and with `jump_cost > 0`, `successor_g ≥ min_rhs` implies `candidate_cost > min_rhs`, so the candidate can be skipped.

The downstream enqueue logic (comparing `g[cell_index]` vs `min_rhs`, computing key, pushing to `_open`) is untouched.

### `_compute_shortest_path()`

When the heap-processing loop updates `g[cell_index]`, it re-relaxes every predecessor of the cell via an inlined neighbour block. The existing block only calls `recompute_rhs` on the 8 walk predecessors; in jump mode it must also call it on every jump predecessor, otherwise cells reachable *only* by a jump edge never enter the open queue and the wavefront from the goal cannot cross a pure jump edge. Insert the additive block inside `_compute_shortest_path`, after the existing walk-predecessor relaxations and before the `if also_self:` branch:

```python
if self._allow_jumps:
    for dx, dy in _JUMP_OFFSETS:
        neighbour_x = x + dx
        if neighbour_x < 0 or neighbour_x >= width:
            continue
        neighbour_y = y + dy
        if neighbour_y < 0 or neighbour_y >= height:
            continue
        recompute_rhs(neighbour_y * width + neighbour_x)
```

This mirrors the `notify_map_changes` and `set_dynamic_blockers` jump-predecessor blocks exactly; the symmetry of `_JUMP_OFFSETS` under negation means iterating successors from `cell_index` enumerates its predecessors.

### `step()`

```python
def step(self):
    if self._allow_jumps:
        raise RuntimeError(
            "step() is undefined when allow_jumps=True; use extract_path()"
        )
    # existing body unchanged
```

### `extract_path()`

Inside the `while current_index != goal` loop, after the existing walk-edge scan selects `(best, best_cost)`, if `_allow_jumps` is set, also scan jump edges using the same best-tracking:

```python
if self._allow_jumps:
    jump_cost = self._jump_cost
    for dx, dy in _JUMP_OFFSETS:
        neighbour_x = x + dx
        if neighbour_x < 0 or neighbour_x >= width:
            continue
        neighbour_y = y + dy
        if neighbour_y < 0 or neighbour_y >= height:
            continue
        successor_index = neighbour_y * width + neighbour_x
        if successor_index in dynamic_blocked or (block_mask >> environment_array[successor_index]) & 1:
            continue
        candidate_cost = jump_cost + g[successor_index]
        if candidate_cost < best_cost:
            best_cost = candidate_cost
            best = successor_index
```

The `visited` loop-guard is retained.

### `extract_path_lines()`

No change. Still returns `(x1, y1, x2, y2)` segments; renderers can colour by distance.

### `notify_map_changes()`

Per changed cell, after recomputing that cell itself and its 8 walk predecessors, if `_allow_jumps` is set, also recompute each jump predecessor:

```python
if self._allow_jumps:
    for dx, dy in _JUMP_OFFSETS:
        neighbour_x = x + dx
        if neighbour_x < 0 or neighbour_x >= width:
            continue
        neighbour_y = y + dy
        if neighbour_y < 0 or neighbour_y >= height:
            continue
        recompute_rhs(neighbour_y * width + neighbour_x)
```

Here `x, y` are the coordinates of the changed cell (already computed by the enclosing walk-predecessor block), and `recompute_rhs` is the local alias for `self._recompute_rhs`. The `bytearray` `memcmp` short-circuit at the top of the method is unchanged and still the common-case fast path.

### `set_dynamic_blockers()`

Per toggled cell, after the existing `_recompute_rhs(cell_index)` + walk-predecessor loop, if `_allow_jumps` is set, also recompute jump predecessors:

```python
for cell_index in changed_nodes:
    self._recompute_rhs(cell_index)
    for predecessor in self._pred(cell_index):
        self._recompute_rhs(predecessor)
    if self._allow_jumps:
        x = cell_index % self._w
        y = cell_index // self._w
        for dx, dy in _JUMP_OFFSETS:
            neighbour_x = x + dx
            if neighbour_x < 0 or neighbour_x >= self._w:
                continue
            neighbour_y = y + dy
            if neighbour_y < 0 or neighbour_y >= self._h:
                continue
            self._recompute_rhs(neighbour_y * self._w + neighbour_x)
```

## Performance note

Running the jump planner is substantially more expensive than the walk planner:

- Each `_recompute_rhs` visits 24 candidate edges instead of 8 (walk 8 + jump 16).
- Per map change, `notify_map_changes` recomputes 24 predecessors per changed tile instead of 8.
- `set_dynamic_blockers` scales the same way.

Running walk + jump planners on a single bot roughly 3–4×'s per-tick pathfinding work versus walk-only today (walk planner 1× + jump planner ~3× due to the 24-vs-8 edge ratio and wider predecessor sets), with the jump planner as the dominant term. No throttling is built in — the call site can invoke `notify_map_changes` or `plan` on the jump planner less often if needed.

## Testing strategy

1. **Regression:** existing callers (harvester seek, harvester return, attacker) instantiate without `allow_jumps`; their planners must behave bit-identically. Smoke-test a full match.
2. **Wall-bypass:** construct a small map where the only walk path is infinity-cost (solid wall separating start and goal with a single traversable endpoint reachable only by jump). `extract_path()` with `allow_jumps=True` must return a path containing a jump segment (`max(|dx|, |dy|) > 1`) and walk-only planner must return `[]`.
3. **Cost preference:** open map with no walls. Walking from `(0, 0)` to `(3, 0)` costs 3; a direct `(3, 0)` jump costs 5. Jump planner's `extract_path()` must return the all-walk route.
4. **Endpoint block-mask:** jump endpoint on a wall must be rejected. Jump endpoint on a dynamic blocker must be rejected.
5. **Path pass-through:** jump over a wall and jump over a dynamic blocker must both succeed when endpoints are valid.
6. **Heuristic admissibility:** verify `_compute_shortest_path` terminates and the final `g[start]` is no smaller than `octile(start, goal)` on an open map (indirectly exercises key consistency).
7. **`step()` contract:** `step()` raises `RuntimeError` in jump mode; unchanged in walk mode.
8. **Incremental repair:** toggling a wall mid-search updates the jump plan correctly (compare against a from-scratch run).

## Out of scope for this spec

- Builder-side integration: how the builder inspects `extract_path()` to pick bridge placements. That belongs to the builder bot, not the planner.
- Hand-unrolling the 16 jump offsets in `_recompute_rhs`. Start with a `for` loop; profile; unroll only if the jump planner's `_recompute_rhs` still dominates.
- Variable jump cost by distance. Flat cost is sufficient for the current model.
