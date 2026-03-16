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
uv venv
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

## Install Battlecode Dependencies

```
uv pip install cambc
```

## Add dependencies from uv.lock

```
uv sync 
```

## Install pre-commit

```
pre-commit install
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

