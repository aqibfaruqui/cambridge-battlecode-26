
# BattleCode Cambridge

# Quickstart

You will require [uv](https://docs.astral.sh/uv/getting-started/installation/).

Install dependencies and run. You must be in your `venv` for this to work:
```sh
uv sync
source .venv/bin/activate

cambc run bot1 bot2 <map path> --replay <replay path>
```

All maps and replays conform to the Protobuf in `cambc.proto`.

