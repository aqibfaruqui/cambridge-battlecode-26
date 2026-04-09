
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

A retrieval-augmented generation tool for querying the game docs in `docs/`. Uses VoyageAI embeddings and Claude to answer questions. Requires `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` in `.env`. Always prefer this tool if available to reading documentation manually. The more precise your query, the better the response for low `k`.

Rebuild the index after docs change:
```sh
uv run scripts/rag.py index
```

Ask a question (retrieves top-5 chunks by default):
```sh
uv run scripts/rag.py ask "How does conveyor resource distribution work?"
uv run scripts/rag.py ask -k 10 "What are all the turret types?"
```

