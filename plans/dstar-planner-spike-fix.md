# Task: eliminate `DStarLite` planner-reconstruction tail spikes in the v12 harvester

## Why this matters

A profiling pass on the v12 harvester landed a per-turn `time.perf_counter_ns()` harness that revealed the bot's runtime is **wildly bimodal**: mean ≈ 1.6 ms but **p99 ≈ 22 ms and max ≈ 38 ms** on a no-seed run; **p99 ≈ 76 ms and max ≈ 248 ms** when sweeping seeds. The worst 1% of turns burn 14–22% of total runtime. Match TLE is configurable but other tournaments have shipped tighter budgets — these tails are real risk.

The single most important diagnostic: when you run the harness, the worst turns are clustered around the *same controller round*, **across every harvester subinterpreter simultaneously**. Round ~301–302 in particular, where the foundry/axionite-unlock transition forces every harvester's seek planner to switch goals from titanium to axionite — and the current implementation throws away the planner and builds a fresh one. Other spikes come from the *return* planner being nulled after path failures (search `return_to_core.py` for `self.return_planner = None`; there are ≥3 sites).

cProfile attributes most of the cost to `d_star.py:_recompute_rhs_general` / `_recompute_rhs_uniform` / `_compute_shortest_path` — the D* Lite first-compute fan-out from a fresh open heap.

## Constraints you must respect

- **No `try/finally` and no `with` statements in bot code.** `cambc` bytecode-validates bots before running them and rejects setup-with bytecode. The harness file uses bare `_fh = open(...); _fh.write(...); _fh.close()` for this reason — match that style.
- **Standard library only** for bot code (no numpy/numba/cython).
- **Bots run in per-team subinterpreters**, so `py-spy` doesn't see frames; everything must be done via in-bot instrumentation.
- **Match outcome must not change.** Run a few sample matches before/after with `cambc run v12 v12 <map> --seed N --replay /tmp/x.replay26` for several maps and seeds; verify the `[harv …]` stderr trace and final scores are stable. The optimization is correctness-preserving or it doesn't ship.

## Where to look

Read these in full before touching anything — they are tightly coupled.

- `bots/v12/utils/pathfinding/d_star.py` — the `DStarLite` class. Already heavily micro-optimized. Note in particular:
  - `__slots__` lists every state-bearing field (lines ~79–104).
  - `_compute_shortest_path` (line 598) is the hot loop and the spike source; inlines `calc_key`, uses flat 3-tuple heap entries, bypasses stale entries via the `_in_open` bytearray.
  - `notify_map_changes` (line 272) and `set_dynamic_blockers` (line 367) are *already incremental* — they read from `EnvironmentMap._change_log` (an append-only log of mutated tile indices) and only touch affected predecessor cells, then call `_compute_shortest_path` to repair.
  - `set_position` (line 193) is also incremental — only triggers a recompute when the bot stands on a previously-blocked tile.
  - `_blocked` is a bytearray bitmap built once at construction via a 256-byte translate table over `EnvironmentMap._array` (lines 154–157). Rebuilding it is cheap.
  - `set_goal` (line 190) is the elephant in the room: `self.__init__(self._env, gx, gy, block_mask=self._block_mask)` — throws away `_g`, `_rhs`, `_blocked`, the open heap, and `_log_version`. **This is the wrong API for what the harvester actually does.**

- `bots/v12/utils/harvester_states/seek.py` lines 335–369 (`_seek_direction`): the seek planner is rebuilt from scratch (`DStarLite(...)`) every time `seek_planner_goal != goal`. This is the round-302 spike source.

- `bots/v12/utils/harvester_states/return_to_core.py`: search for `self.return_planner = None` — every one of these paths forces a full first-compute on the next call. Some are conservative (e.g., the foundry-input-protection branch in `_build_return_step` near line ~580); evaluate whether they really need a full reset.

- `bots/v12/utils/map/raw_map_representation.py` `_change_log` (line 68) — the substrate `notify_map_changes` already uses for incremental repair.

## The diagnostic harness (use it; trust it more than cProfile)

`scripts/spike.py` reads `/tmp/harvester_spikes/*.spikes` and reports per-turn distribution + per-section breakdown. The harness itself is at the top of `bots/v12/builders/harvester.py` (search for `_SPIKE_BUF`). Workflow:

```sh
# baseline (record current state of branch first)
rm -rf /tmp/harvester_spikes /tmp/harvester_profiles
uv run scripts/profile.py run harvester                 # populates both
uv run scripts/spike.py report harvester
uv run scripts/spike.py worst harvester --n 15          # see which round spikes
uv run scripts/spike.py sections harvester              # per-section tail

# repeat after each change; the diff in `state_seek` p99/max and `state_return`
# p99/max is your primary signal. cProfile's tottime/cumtime are useful but
# average over the whole run and will hide the wins you care about here.
```

Run with several `--seed` values (`uv run scripts/profile.py run harvester --seed 11`, etc.) — single-run noise dominates the tail. You want to see the p99 and max move on **multiple seeds**.

`scripts/profile.py callers harvester _compute_shortest_path` and `... callees harvester _compute_shortest_path` are useful for understanding which call site dominates each direction.

## What the existing notes about scope rule out

A previous pass added per-bot caches of `c.get_team()`/`map_w`/`map_h` and inlined `_update_chain_memory`/`_return_dynamic_blockers`. That work shaved ~40% off the `chain_memory` mean and ~75% off `foundry_check`, which moved p50/p90 by ~12% but **did not move p99/max** because those tails are pure D* Lite first-compute. The remaining wins are algorithmic, not micro.

The previous notes explicitly flagged two avenues:
1. A cheap goal-change variant of `DStarLite` that preserves `_blocked` and reuses prior g-values (D* Lite was *designed* for moving start, but moving goal is harder — there's published work on this).
2. Auditing the `self.return_planner = None` reset paths to see which can be downgraded to less destructive operations (e.g., flushing dynamic blockers, or letting the planner re-route through `notify_map_changes`).

You don't have to take either approach. Other ideas worth weighing: reusing the seek planner across goal changes that are *adjacent* to the previous goal (incremental relocation); precomputing planners off-spike (e.g., warm an axionite planner during the titanium phase); amortising the first compute over multiple turns by yielding mid-computation; allowing per-turn work caps. Pick what gives the largest p99/max reduction for the least invasive change. **Justify your choice with measured numbers from `spike.py`, not theory.**

## Definition of done

- p99 and max per-turn time meaningfully reduced (target: at least halve max on the no-seed run, ideally drop multi-seed p99 below 30 ms).
- p50 not regressed.
- No change to match outcomes on at least 3 maps × 3 seeds (compare final scores and key `[harv …]` stderr traces).
- New code respects the `cambc` constraints (no `try/finally`, no `with`).
- The `spike.py` `worst` output before-and-after is included in your final report so the win is auditable.

Start by reading the four files above end-to-end, then run the harness on the current branch to make sure your numbers reproduce. Don't write any code until you can name — concretely, with file:line — which specific call site you are targeting and what its current p99 contribution is according to `spike.py sections`.
