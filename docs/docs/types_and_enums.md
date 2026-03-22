# Types & Enums

All types are imported from the `cambc` module:
```python
from cambc import *
```

This gives you: `Team`, `EntityType`, `ResourceType`, `Environment`, `Direction`, `Position`, `GameConstants`, `GameError`, and `Controller`.

---

## Team
```python
class Team(Enum):
    A = "a"
    B = "b"
```

---

## EntityType
```python
class EntityType(Enum):
    BUILDER_BOT = "builder_bot"
    CORE = "core"
    GUNNER = "gunner"
    SENTINEL = "sentinel"
    BREACH = "breach"
    LAUNCHER = "launcher"
    CONVEYOR = "conveyor"
    SPLITTER = "splitter"
    ARMOURED_CONVEYOR = "armoured_conveyor"
    BRIDGE = "bridge"
    HARVESTER = "harvester"
    FOUNDRY = "foundry"
    ROAD = "road"
    BARRIER = "barrier"
    MARKER = "marker"
```

---

## ResourceType
```python
class ResourceType(Enum):
    TITANIUM = "titanium"
    RAW_AXIONITE = "raw_axionite"
    REFINED_AXIONITE = "refined_axionite"
```

---

## Environment
```python
class Environment(Enum):
    EMPTY = "empty"
    WALL = "wall"
    ORE_TITANIUM = "ore_titanium"
    ORE_AXIONITE = "ore_axionite"
```

---

## Direction
```python
class Direction(Enum):
    NORTH = "north"
    NORTHEAST = "northeast"
    EAST = "east"
    SOUTHEAST = "southeast"
    SOUTH = "south"
    SOUTHWEST = "southwest"
    WEST = "west"
    NORTHWEST = "northwest"
    CENTRE = "centre"
```

### Direction Methods

| Method | Returns | Description |
|---|---|---|
| `delta()` | `tuple[int, int]` | Returns the `(dx, dy)` step for this direction. North is `(0, -1)`, East is `(1, 0)`, etc. |
| `rotate_left()` | `Direction` | Returns the direction rotated 45° counterclockwise. |
| `rotate_right()` | `Direction` | Returns the direction rotated 45° clockwise. |
| `opposite()` | `Direction` | Returns the opposite direction (180°). |

---

## Position

A named tuple with `x` and `y` integer fields.
```python
class Position(NamedTuple):
    x: int
    y: int
```

### Position Methods

| Method | Returns | Description |
|---|---|---|
| `add(direction)` | `Position` | Returns a new position offset by the direction delta. |
| `distance_squared(other)` | `int` | Returns the squared Euclidean distance to another position. |
| `direction_to(other)` | `Direction` | Returns the closest 45° Direction approximation toward other. |

### Usage
```python
pos = Position(5, 10)
new_pos = pos.add(Direction.NORTH)      # Position(5, 9)
dist = pos.distance_squared(new_pos)    # 1
dir = pos.direction_to(Position(8, 7))  # Direction.NORTHEAST
```

---

## GameError
```python
class GameError(Exception):
    pass
```

Raised when a player issues an invalid action (e.g., building on an occupied tile, moving with cooldown > 0).