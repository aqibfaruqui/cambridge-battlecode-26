# Cambridge Battlecode 

## Trello Board

Tracking ideas, info and bug fixes

Link: https://trello.com/b/nZzM64RG/battlecode

## Requirements

Check for uv:

```
uv --version
```

If not installed (Mac with Homebrew):

```
brew install uv
```

Create .python-version

```
uv python pin 3.12.3
```

And install python (versions != 3.12.x don't build cambc):

```
uv python install 3.12.3
```

---

## Enter Virtual Environment

```
uv sync
```

On Linux/MacOS:

```
source .venv/bin/activate
```

On Windows:

```
.venv\Scripts\activate
```

---

## Getting Started

### Generate starter bot 

```
cambc starter
```

### Run local match

```
cambc run starter starter --watch
```
Note: Running local match does not enforce 2ms timing and 1GB memory limit.
Use `cambc test-run` to run on same machines that are used in the ladder matches.

### Watch Replay

```
cambc watch replay.replay26
```

### Edit starter bot

```
bots/starter/main.py
```

### Submit a bot

```
cambc submit bots/starter
```

# Development

Re-scrape documentation with:

```sh 
uv run scripts/scrape_docs.py
```

### Profile a v12 bot

Bots are bytecode-validated by `cambc` (no `try/finally`) and run in sub-interpreters, so `py-spy` can't see bot frames — profiling is done via in-bot `cProfile` instrumentation. Two v12 bots are pre-instrumented and dump `.pstats` files to per-target directories:

| Target      | Source                              | Dump directory             |
| ----------- | ----------------------------------- | -------------------------- |
| `harvester` | `bots/v12/builders/harvester.py`    | `/tmp/harvester_profiles/` |
| `attacker`  | `bots/v12/builders/attacker.py`     | `/tmp/attacker_profiles/`  |

`scripts/profile.py` requires the target as a positional argument — there is no default, you must pick `harvester` or `attacker`.

```sh
uv run scripts/profile.py run harvester                       # run match, print top hotspots
uv run scripts/profile.py run attacker -m default_large1
uv run scripts/profile.py report harvester --filter d_star    # re-analyze, filtered
uv run scripts/profile.py callers attacker _succ              # who calls a hot function
```

Pass `--profile-dir <path>` to override the per-target directory (useful for side-by-side runs of the same target).

### Spike analysis (p99 / max per turn)

cProfile averages over the whole run; spiky turns get drowned out. The harvester also runs a lightweight per-turn `time.perf_counter_ns()` harness that captures total + per-section wall time for every `run()` call and writes binary traces to `/tmp/harvester_spikes/`. `scripts/spike.py` analyses them:

```sh
uv run scripts/spike.py report harvester        # mean, p50/p90/p99/p99.9/max + per-section sums
uv run scripts/spike.py worst harvester --n 15  # 15 slowest turns with full section breakdown
uv run scripts/spike.py sections harvester      # per-section percentile distribution
```

Use this when you care about p99/max latency rather than mean — e.g. tracking down which section blows up on a specific turn. The harness is on at all times the bot runs locally; one `profile.py run` populates both `cProfile` pstats and the spike traces. Spike analysis is harvester-side; the attacker has the `cProfile` harness only.
