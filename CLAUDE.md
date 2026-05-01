# BattleCode Cambridge

## Quickstart

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/). Install and activate:

```sh
uv sync && source .venv/bin/activate
```

Manage deps with `uv add <pkg>` (`--upgrade` to bump). Don't edit `pyproject.toml` by hand.

Run a match:

```sh
cambc run <bot_a> <bot_b> <map_path> --replay <replay_path>
```

Maps and replays are Protobuf — schema in `proto/cambc.proto`.

## Game documentation (RAG)

`scripts/rag.py` retrieves chunks from `docs/`. Requires `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` in `.env`. **Prefer this over reading docs manually**, and never assume game rules — query first, or ask if the docs don't cover it.

```sh
uv run scripts/rag.py index                                       # rebuild after docs change
uv run scripts/rag.py ask "How does conveyor distribution work?"
uv run scripts/rag.py ask -k 10 "What are all the turret types?"
```

## Replay analysis

`scripts/replay_cli.py` is the main tool for inspecting a finished match. Five subcommands sharing a cached parse:

```sh
uv run scripts/replay_cli.py grid  REPLAY --turn N    [--region X1,Y1,X2,Y2] [--full]
uv run scripts/replay_cli.py trace REPLAY --bot ID    --turns A-B
uv run scripts/replay_cli.py flow  REPLAY --turns A-B [--region ...] [--edges]
uv run scripts/replay_cli.py diff  REPLAY --turn-a A  --turn-b B  [--kinds ...]
uv run scripts/replay_cli.py chain REPLAY --turn N    --start X,Y [--upstream]
```

- `grid` — region snapshot at turn N. 6-char cells `TT t d r` with arrows `↑↗→↘↓↙←↖`; `*` overlays bots. See `grid --help` for the full legend.
- `trace` — one bot's position + stdout log line per turn.
- `flow` — per-tile resource-flow histogram over a window, broken down by direction and resource type (Ti / Ax / refined).
- `diff` — chronological event log between two turns (place / remove / move / HP / fires / indicators).
- `chain` — walk a conveyor chain from a starting tile (handles harvesters, splitter T-shape, bridges); `--upstream` traces feeders backwards.

In bot code, `c.draw_indicator_dot(pos, r, g, b)` / `c.draw_indicator_line(a, b, r, g, b)` plus plain `print(...)` get embedded in the replay and surface via `trace` and `diff`.

The on-disk parse cache lives in `scripts/.replay_cache/`; pass `--cache-rebuild` to nuke it.

## Profiling

`cambc` bytecode-validates bots and **disallows `try/finally`** — instrument hot paths with bare `cProfile.enable()` / `disable()` calls. Bots run in per-team sub-interpreters in one process, so `py-spy` can't see bot frames.

```sh
uv run scripts/profile.py run                          # v10 vs v10, default_separated, TLE off
uv run scripts/profile.py run -m default_large1 --bot-b v9

# Analyse existing .pstats without rerunning:
uv run scripts/profile.py report --sort tottime --top 30
uv run scripts/profile.py report --filter d_star       # only frames matching regex
uv run scripts/profile.py callers _succ                # who calls this
uv run scripts/profile.py callees _recompute_rhs       # what it calls
```
