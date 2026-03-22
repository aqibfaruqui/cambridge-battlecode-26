# Builder Bot

The only mobile unit — responsible for constructing all buildings.

Builder bots are the **only mobile unit**. They construct buildings, heal friendly entities, and can self-destruct for area damage.

---

## Properties

| Property | Value |
|----------|-------|
| HP | 30 |
| Base cost | 10 Ti |
| Scaling contribution | 10% |
| Vision radius² | 20 |
| Action radius² | 2 |

---

## Movement

Builder bots can move to an adjacent tile (including diagonals) if their move cooldown is 0. Moving increases the cooldown by 1.

> **Warning:** Builder bots can **only walk on**:
> - Conveyors (any variant, any direction, either team)
> - Roads (either team)
> - The allied core
>
> These are called **walkable** tiles. The direction of the conveyor does not matter, and neither does the presence of resources on the tile.
```python
# Move towards a target
direction = c.get_position().direction_to(target)
if c.can_move(direction):
    c.move(direction)
```

---

## Actions

When action cooldown is 0, a builder bot can perform one of:

### Build

Build any building or turret on a tile within action radius that doesn't already have a building.

> **Note:** Only walkable buildings (conveyors and roads) can be built on a tile that contains a builder bot.

### Heal

Heal all friendly entities on a tile within action radius by **10 HP**.
```python
if c.can_heal(target_pos):
    c.heal(target_pos)
```

### Destroy

Destroy any allied building within action radius. This can be done **any number of times per round** and does **not** cost action cooldown.
```python
if c.can_destroy(building_pos):
    c.destroy(building_pos)
```

---

## Self-Destruct

A builder bot can self-destruct at any time, dealing **20 damage** to the building on the tile it is standing on.
```python
c.self_destruct()
```

---

## Markers

Builder bots (like all units) can place one marker per round within action radius, separate from the action cooldown.
