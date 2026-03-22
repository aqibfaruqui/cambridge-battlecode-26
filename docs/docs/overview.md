```markdown
# Cambridge Battlecode – Game Overview

## Objective
Collect resources and **destroy the enemy's core**.

- Find ore deposits
- Build harvesters
- Deliver resources back to the core via conveyors
- Expand your territory

---

## Win Conditions
If both cores survive after **2000 rounds**, the winner is decided by tiebreakers (in order):

1. **Axionite delivered** – total refined axionite delivered to the core
2. **Titanium delivered** – total titanium delivered to the core
3. **Harvesters alive** – number of harvesters currently alive
4. **Axionite stored** – total axionite currently stored
5. **Titanium stored** – total titanium currently stored
6. **Coinflip** – random tiebreaker

---

## Map
- Rectangular grid, **20×20 to 50×50** inclusive
- Origin `(0, 0)` is the top-left (northwest) corner
- Guaranteed to be **symmetric** (reflection or rotation)

| Cell Type     | Description                        |
|---------------|------------------------------------|
| Empty         | Can build anything                 |
| Wall          | Impassable, cannot build           |
| Titanium ore  | Harvesters mine titanium           |
| Axionite ore  | Harvesters mine raw axionite       |

---

## Units
Units run an **independent instance** of your submitted code. The core, builder bots, and turrets
are units. **Harvesters are not units** — they operate automatically.

Each round, units take turns **in the order they were spawned**. After all turns, resources are
distributed.

### Vision & Action Radius

| Unit         | Vision r² | Action r²        |
|--------------|-----------|------------------|
| Core         | 36        | 8 (from centre)  |
| Builder bot  | 20        | 2                |
| Gunner       | 13        | 2                |
| Sentinel     | 32        | 2                |
| Breach       | 10        | 2                |
| Launcher     | 26        | 2                |

Turrets also have a separate **attack range** distinct from their action radius.

### Cooldowns
All units have **action** and **move** cooldowns (non-negative integers, decrease by 1 each round).
Actions/movement require the respective cooldown to be **0**.

> The move cooldown is only used by the **builder bot** — it is the only mobile unit.

### Markers
All units may place **one marker per round** on a tile within action radius (separate from action
cooldown). You can overwrite a friendly marker but not an enemy marker.

### Self-Destruct
All units may self-destruct at any time. Builder bots deal **20 damage** to the tile they occupy
upon self-destruct.

---

## Buildings
Buildings are **immovable** entities. All entities are buildings except builder bots.
The core and turrets are considered **both a unit and a building**.

---

## Entity IDs
All entities have a **unique integer ID**. Properties are queried via getter functions:

```python
# Get all nearby entities and check their type
for entity_id in c.get_nearby_entities():
    if c.get_entity_type(entity_id) == EntityType.HARVESTER:
        pos = c.get_position(entity_id)
```

> The ID-based API was chosen for performance — constructing Python objects for every entity query
> would be too slow within the 2ms time limit.

---

## Computation Limit
- Each unit gets **2ms of CPU time** per round
- If exceeded, execution is interrupted and `run()` is called fresh next round (**no resume**)
- Each unit has an **extra time buffer** equal to 5% of the time limit
  - Overages are deducted from the buffer; savings are refunded (capped at 5%)
- Once both the 2ms budget and buffer are exhausted, the unit is interrupted immediately

> `cambc run` does **not** enforce time limits. Use `cambc test-run` to test on the same AWS
> Graviton3 hardware used for ladder matches.

---

## Debugging
- **stdout** (`print()`) is captured by the engine and saved to the replay (viewable in visualiser)
- **stderr** prints to the console in real time (use for local debugging)
- `c.draw_indicator_line(pos_a, pos_b, r, g, b)` — draws a debug line overlay, saved to replay
- `c.draw_indicator_dot(pos, r, g, b)` — draws a debug dot overlay, saved to replay
```
