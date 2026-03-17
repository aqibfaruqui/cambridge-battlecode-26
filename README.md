# Cambridge Battlecode 2026

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

## Create Virtual Environment

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

