
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

