# Resources

Titanium, axionite, and the cost scaling formula.

---

## Titanium

The primary resource used to construct most buildings. Each team starts with **1000 titanium**.

Titanium is harvested from titanium ore deposits and delivered to the core via conveyors.

---

## Axionite

Axionite comes in two forms:

### Raw Axionite
Mined from axionite ore deposits. When fed to a turret or core, it **decays into titanium**. Must be refined first for advanced uses.

### Refined Axionite
Produced by axionite foundries from raw axionite + titanium. Used for powerful units and advanced infrastructure.

> **Note:** Whenever "axionite" is mentioned in the spec without qualification, it refers to **refined axionite**.

---

## Resource Distribution

Resources are stored and moved in **stacks of 10**. At the end of each round, buildings that output resources send them to adjacent buildings that accept them.

> **Warning:** Resources can be outputted to buildings belonging to the **opposing team**.

See conveyors, harvester & foundry, and turrets for details on input/output directions.

---

## Cost Scaling

Every building and unit you construct increases the cost of future builds. The cost of every building and unit is:
```
cost = floor(scale × base cost)
```

Scale starts at **1.0** and increases with each entity built. Query the current scale with `c.get_scale_percent()`, which returns it as a percentage (100.0 at base).

| Entity | Scale Increase |
|--------|---------------|
| Road | +0.5% |
| Conveyor, splitter, armoured conveyor, bridge, barrier | +1% |
| Builder bot, harvester, gunner, sentinel, breach, launcher | +10% |
| Axionite foundry | +100% |

When an entity is destroyed, its scaling contribution is removed — costs go back down.

