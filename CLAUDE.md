
# BattleCode Cambridge

# Quickstart

You will require [uv](https://docs.astral.sh/uv/getting-started/installation/).

Install dependencies and run. You must be in your `venv` for this to work:

```sh
uv sync
source .venv/bin/activate
```

Always use `uv add <package>` to add a new package. Use `uv add --upgrade <package>` to update a package.


```sh 
cambc run bot1 bot2 <map path> --replay <replay path>
```

All maps and replays conform to the Protobuf in `cambc.proto`.

# RAG Documentation Tool

A retrieval-augmented generation tool for querying the game docs in `docs/`. Requires `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` in `.env`. Always prefer this tool if available to reading documentation manually. Do not assume anything about the game, always query documentation. Ask the user if the documentation does not answer your question.

Rebuild the index after docs change:
```sh
uv run scripts/rag.py index
```

Ask a question (retrieves top-5 chunks by default):
```sh
uv run scripts/rag.py ask "How does conveyor resource distribution work?"
uv run scripts/rag.py ask -k 10 "What are all the turret types?"
```

# Profiling

`cambc` bytecode-validates bots before executing them and **disallows `try/finally` blocks** — instrument hot paths with bare `enable()`/`disable()` calls instead. Bots run in per-team sub-interpreters inside a single process, so `py-spy` will not see bot frames; use `cProfile` instrumentation instead.

Two v12 bots are wired up. Each owns a module-level `cProfile.Profile` that dumps `.pstats` files (one per subinterpreter) every 100 `run()` calls to its own directory:

| Target      | Source                              | Dump directory             |
| ----------- | ----------------------------------- | -------------------------- |
| `harvester` | `bots/v12/builders/harvester.py`    | `/tmp/harvester_profiles/` |
| `attacker`  | `bots/v12/builders/attacker.py`     | `/tmp/attacker_profiles/`  |

`scripts/profile.py` requires you to **explicitly pick a target** as a positional argument (`harvester` or `attacker`) — there is no default, so harvester and attacker runs never accidentally share a directory.

Run a match and print an aggregated report:
```sh
uv run scripts/profile.py run harvester                                  # v12 vs v12 on separated, TLE off
uv run scripts/profile.py run attacker -m default_large1 --bot-b v11
```

Analyze existing `.pstats` files without rerunning (target picks the dir):
```sh
uv run scripts/profile.py report harvester --sort tottime --top 30
uv run scripts/profile.py report attacker --filter d_star          # only frames matching regex
uv run scripts/profile.py callers harvester _succ                  # who calls this function
uv run scripts/profile.py callees attacker _recompute_rhs          # what does it call
```

Override the per-target directory with `--profile-dir <path>` if you want to compare two runs of the same target side-by-side.

## Per-turn spike analysis (p99 / max)

cProfile aggregates over the whole run, which hides spiky turns behind the long tail of cheap ones. The harvester is also wired with a lightweight per-turn `time.perf_counter_ns()` harness that records, for every `run()` call, the total wall time and a fixed-order array of per-section times (env_update, chain_memory, foundry_check, …, state_seek, state_return, …, broadcaster, draw_log). Output goes to `/tmp/harvester_spikes/*.spikes` (binary, one file per subinterpreter). It runs alongside `cProfile` — a single `profile.py run` populates both directories.

`scripts/spike.py` reads those traces and reports:

```sh
uv run scripts/spike.py report harvester      # mean, p50/p90/p99/p99.9/max + per-section sums
uv run scripts/spike.py worst harvester --n 15 # the 15 slowest turns with section breakdown
uv run scripts/spike.py sections harvester     # per-section percentile distribution
```

Use `report` to see how concentrated total runtime is in the worst 1% of turns; use `worst` to find which section caused a specific spike (typically `state_return` when D* Lite recomputes from a fresh planner, or `state_seek` when an ore reroute fires); use `sections` when you want to know which section's *tail* is the dominant spike source even if its mean is small.

Override the directory with `--spike-dir <path>` for side-by-side runs.

