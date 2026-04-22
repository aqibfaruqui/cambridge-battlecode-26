# Harvester Jump-Bridge Integration — Design

**Date:** 2026-04-22
**File to modify:** `bots/v11/utils/harvester_states/return_to_core.py` (primary) and the `Harvester` class in `bots/v11/builders/harvester.py` (new fields + init).

## Problem

The harvester's return-to-core flow currently uses a walk-only `DStarLite` planner to step home and lay conveyors along the way. When a wall sits between the harvester and core, the walker routes around it; the conveyor chain follows that detour. Laying a long detour of conveyors can cost more than placing a single long-range bridge that spans the obstacle and carries resources directly across.

We want the harvester's return trip to use a jump-aware planner that identifies where a bridge is more efficient than routing conveyors around. On those segments the harvester builds the long-range bridge (for resources), walks around the obstacle itself (bridges are for resources, not bots), and resumes normal conveyor-building at the landing cell.

## Scope

Replace `self.return_planner` with a jump-enabled planner (`allow_jumps=True`) as the primary router for return-to-core. Add a small temporary walk-only planner per jump segment to physically walk the harvester from the bridge launch `A` to the bridge landing `B`. Add a persistent blacklist for landings that turn out to be unreachable.

Non-goals:
- Changing any other harvester state (SEEK, PATROL, DEFEND).
- Changing planner consumers outside `return_to_core.py` (attacker, harvester seek, harvester return in v10).
- Adding standalone unit tests. Harvester flows are validated via `cambc run` matches in this repo.
- Dynamic blacklist expiry. Blacklist is permanent per-harvester.

## Key Game Mechanics (non-obvious)

- **Long-range bridges:** `c.build_bridge(A, B)` supports spans up to `dist_sq(A, B) ≤ 9`, matching `_JUMP_OFFSETS`.
- **Bridges carry resources, not bots.** The harvester cannot physically walk across a bridge. It must walk around the obstacle via open terrain to reach `B`.
- **Walls under bridges stay walls in `EnvironmentMap`.** Any walker built on the unmodified env map will see the original walls and must therefore route around them — which is exactly what we want.

## Harvester fields (`Harvester.__init__`)

Remove:
- `self.return_planner: DStarLite | None`

Add:
- `self.return_jump_planner: DStarLite | None` — primary router for return-to-core. `allow_jumps=True`, goal = core, `block_mask=_RETURN_BLOCK_MASK`, `unknown_cost=3.0`. Cleared by `_reset_return_state`.
- `self.return_jump_blacklist: set[tuple[int, int]]` — persistent blacklisted landings. Initialized to `set()` in `Harvester.__init__`. **Not** cleared by `_reset_return_state` (persists per-harvester for the rest of the game).
- `self.return_jump_walker: DStarLite | None` — temporary walk-only planner active only during an `A → B` traversal. Cleared by `_reset_return_state` and on arrival at `B`.
- `self.return_jump_landing: tuple[int, int] | None` — the `B` we're traversing to. Used to detect arrival and as a "mid-jump?" flag. Cleared alongside the walker.

## Helper structure (`return_to_core.py`)

### Replaced

- **`_ensure_return_planner` → `_ensure_return_jump_planner`.** Constructs the jump planner (with `allow_jumps=True`) on first use. Each turn, applies `set_dynamic_blockers(_return_dynamic_blockers(c) + list(self.return_jump_blacklist))` (turn-fresh blockers unioned with the persistent blacklist) and calls `notify_map_changes()`.

- **`_planner_step_at(pos) → Direction | None` → `_planner_direction_at(pos) → Direction | None`.** The jump planner's `step()` raises `RuntimeError` (that's by design — `Direction` can't express a jump). The replacement sets the jump planner's start to `pos`, calls `extract_path()`, and returns `Position(path[0]).direction_to(Position(path[1]))` **iff** the first segment is a walk (`max(|dx|, |dy|) ≤ 1`). Returns `None` if the first segment is a jump, the path is empty, or the planner is not available. Callers already treat `None` as "fall back to `direction_to(core_pos)`", which preserves correct behaviour for walk-only callers; sites that care about jumps handle them explicitly via the dispatcher (Section 3 below).

### New

- **`_start_or_continue_jump(self, c, landing_xy) -> bool`.** State machine for bridge build + walk-around traversal. First turn: pre-validates walk-around reachability, builds the long-range bridge, creates the walker. Subsequent turns: steps the walker one cell at a time with road-paving (no conveyors, no corner-cut bridges). Detects arrival at `B` and clears state. Returns `True` if the turn was consumed, `False` otherwise.

- **`_blacklist_landing(self, landing_xy) -> None`.** Adds `landing_xy` to `self.return_jump_blacklist`, clears `self.return_jump_walker` and `self.return_jump_landing`. The next `_ensure_return_jump_planner` call propagates the blacklist to the planner's dynamic blockers.

### Untouched

- `_resolve_diagonal`, `_handle_diagonal_step`, `_handle_bridge_state`, `_clear_return_tile`, `_is_return_tile_usable`, `_return_dynamic_blockers`. These apply on walk segments of the jump plan, unchanged.

## Per-turn dispatch in `_build_return_step`

```
0. (Existing) Enemy-under-bot attack check. Unchanged; runs before gate 1.

1. If self.return_jump_walker is not None:
       return _start_or_continue_jump(self, c, self.return_jump_landing)
   (Mid-traversal: step across the walk-around, or blacklist on failure.)

2. (Existing) just_placed seeding block. Unchanged logic, but uses
   _planner_direction_at instead of _planner_step_at.

3. (Existing) _handle_bridge_state check (diagonal corner-cut bridge
   pending? post-bridge conveyor?). Unchanged.

4. Ensure jump planner is up to date (_ensure_return_jump_planner).

5. Extract jump plan path from current_pos:
       planner_path = planner.extract_path()
   If len(path) < 2: fall through to existing "move toward core" fallback.

6. Inspect first segment (A = current_pos, next = path[1]):
   dx = next.x - A.x; dy = next.y - A.y

   (a) WALK segment (max(|dx|, |dy|) <= 1):
       Follow the existing walk body, but derive move_dir from
       current_pos.direction_to(next) instead of the removed
       return_planner.step(). The rest of the body (diagonals,
       conveyors, corner-cut bridges, next_dir lookahead) runs
       unchanged.

   (b) JUMP segment (max(|dx|, |dy|) > 1):
       return _start_or_continue_jump(self, c, (next.x, next.y))
       (First turn: build bridge, create walker, consume turn.
        Subsequent turns won't reach this branch because gate 1 fires
        first.)
```

**Invariant:** once we enter jump-traversal (gate 6b's first invocation), gate 1 owns the harvester until arrival at `B` or blacklist. No conveyor placement, no diagonal-corner-cut logic, no `_handle_bridge_state` during traversal.

**`return_next_dir` interaction.** The existing field carries a direction from a previous turn (e.g. a split diagonal). When set, the turn uses the stashed direction instead of the jump planner. This is preserved.

## Bridge build + walk-around (`_start_or_continue_jump`)

```python
def _start_or_continue_jump(self, c, landing_xy) -> bool:
    # First turn: no walker yet
    if self.return_jump_walker is None:
        A = self.current_pos
        B = Position(landing_xy[0], landing_xy[1])

        # Pre-validate walk-around reachability.
        probe = DStarLite(
            self.environment_map, B.x, B.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
        )
        probe.set_dynamic_blockers(_return_dynamic_blockers(c))
        probe.set_position(A.x, A.y)
        probe.plan()
        if len(probe.extract_path()) < 2:
            self._blacklist_landing(landing_xy)
            return False

        # Walk-around exists. Build the resource bridge this turn.
        if not c.can_build_bridge(A, B):
            ti, _ = c.get_global_resources()
            bridge_cost_ti, _ = c.get_bridge_cost()
            if ti < bridge_cost_ti:
                return False           # insufficient resources → wait, no blacklist
            self._blacklist_landing(landing_xy)
            return False

        c.build_bridge(A, B)
        self.return_jump_walker = probe
        self.return_jump_landing = landing_xy
        return True                     # bridge build consumes the turn

    # Continuing turns: walk-around toward B
    walker = self.return_jump_walker
    walker.set_dynamic_blockers(_return_dynamic_blockers(c))
    walker.notify_map_changes()
    walker.set_position(self.current_pos.x, self.current_pos.y)

    path = walker.extract_path()
    if len(path) < 2:
        self._blacklist_landing(landing_xy)
        return False

    nxt = path[1]
    move_dir = self.current_pos.direction_to(Position(nxt[0], nxt[1]))
    if move_dir is None:
        return False

    # attacker.py pattern: pave with road if needed, then move.
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

**Notes:**

1. Walker routes around the obstacle, not across the bridge. Bridge at `A→B` carries resources; harvester walks open terrain.
2. Road paving follows the `attacker.py` pattern — build road on empty cells when action cooldown is zero, then move. No conveyor placement, no corner-cut bridge placement.
3. Bridge build and walk start on different turns. Turn 1 consumes the bridge cost; walking begins turn 2+.
4. Cost-insufficient vs hard-fail are distinguished. Insufficient resources → wait, no blacklist. `can_build_bridge` False with sufficient resources → blacklist (terrain issue).
5. The probe planner doubles as the walker — we don't need two walk-only planners for the same goal.

## Blacklist mechanics

- **Storage:** `self.return_jump_blacklist: set[tuple[int, int]]`, initialized once in `Harvester.__init__`, never cleared.
- **Application:** every turn, `_ensure_return_jump_planner` calls `self.return_jump_planner.set_dynamic_blockers(_return_dynamic_blockers(c) + list(self.return_jump_blacklist))`. Turn-fresh blockers unioned with the persistent blacklist. The jump planner's D* Lite treats blacklisted cells as unreachable and routes around them. This does over-aggressively block the cell for walk edges too — see Trade-off below.
- **Blacklist triggers:**
  1. Walk-around probe returns empty path to `B` on first invocation.
  2. `c.can_build_bridge(A, B)` returns False with sufficient resources (hard game-side refusal).
  3. Walker returns empty path mid-traversal.
- **`_blacklist_landing`** clears `return_jump_walker` / `return_jump_landing` so the next turn re-plans fresh.

**Trade-off.** Using `set_dynamic_blockers` for the blacklist blocks `B` as both a walk endpoint and a jump endpoint in the jump planner. Finer-grained "jump-only blacklist" would require a new mechanism in `DStarLite`. For this design we accept the over-aggression — if a `B` turned out to be physically unreachable, blocking it as a walk endpoint too is arguably correct, and the jump planner will find an alternate route.

## Testing strategy

The existing codebase has no harvester-level unit tests; validation is via `cambc run` matches.

1. **Regression match (v11 vs v11).** Run a full match; assert no tracebacks from `return_to_core.py` and that harvesters complete return trips. Grep output for exceptions mentioning that file.
2. **Visual-inspection match.** Pick or construct a map where walls sit between harvester deploy points and the core. Watch the replay: harvester places a harvester, builds conveyor chain, reaches a wall, places a long-range bridge, walks around, resumes conveyor chain from the landing.
3. **Blacklist smoke.** Run a match where `B` is physically unreachable (e.g., pre-placed walls around the landing). Expect the harvester to blacklist `B` and fall back to the conveyor-around route within a few turns.
4. **Non-regression of other states.** SEEK / PATROL / DEFEND should behave identically to today — we're not touching those paths. Confirmed via the regression match.

## Open questions for implementation

1. **Stuck-during-walk-around.** If `can_move(move_dir)` returns False for many consecutive turns, should we blacklist after `N` stall turns? Proposed default: 10 turns → blacklist. Add if profiling/match outcomes show stalls in practice.
2. **`_return_dynamic_blockers` scope.** The function returns only `c.get_nearby_tiles()` blockers — cells outside vision aren't included. This is the same limitation as today's walk planner. Leave unchanged unless testing surfaces issues.
3. **Enemy-under-bot interaction.** `_attack_enemy_under_bot` must run before gate 1 (mid-traversal state). The implementation will place the enemy-attack check as gate 0 in `_build_return_step` to preserve current behaviour.
4. **Bridge build + move in same turn.** Cooldowns may allow both on turn 1 (the diagonal-bridge code already does road + move in one turn). Start conservative (bridge-only turn 1) and optimize only if matches show waste.

## Out of scope

- Harvester bots in `bots/v10/` (untouched).
- Exposing the jump planner to other harvester states.
- Shared team-wide blacklist across harvesters.
