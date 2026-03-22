# Core

Your central building — if it's destroyed, you lose.

The core is each team's central building. **If your core is destroyed, you lose the game.** Each team starts with one core.

---

## Properties

| Property | Value |
|----------|-------|
| HP | 500 |
| Footprint | 3×3 |
| Vision radius² | 36 |
| Action radius² | 8 (from centre) |

---

## Spawning

The core can **spawn one builder bot per round** on any of the 9 tiles it occupies. Spawning costs one action cooldown.
```python
# Spawn a builder on an empty core tile
pos = c.get_position()  # centre of the 3x3 core
for dx in range(-1, 2):
    for dy in range(-1, 2):
        target = Position(pos.x + dx, pos.y + dy)
        if c.can_spawn(target):
            c.spawn_builder(target)
            break
```

---

## Resource Delivery

Resources must be transferred to the core via conveyors to be added to your team's global resource pool, which is used for building.
