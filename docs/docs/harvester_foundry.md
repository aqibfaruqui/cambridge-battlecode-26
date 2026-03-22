# Harvester & Foundry

Resource production — mining ore and refining axionite.

---

## Harvester

Must be placed on an **ore deposit**. Outputs one stack of the corresponding resource to an adjacent building every **4 rounds**. The first output happens immediately on the round the harvester is built.

Prioritises outputting in directions used least recently.

| Property | Value |
|----------|-------|
| HP | 30 |
| Base cost | 80 Ti |
| Scaling | 10% |
| Output interval | 4 rounds |
```python
# Build a harvester on an ore tile
if c.can_build_harvester(ore_pos):
    c.build_harvester(ore_pos)
```

> **Tip:** Harvesters are expensive (80 Ti base, +10% scaling) but they generate resources passively. Build them on ore deposits early to fund your expansion.

---

## Axionite Foundry

Takes one stack each of **titanium and raw axionite**, then outputs one stack of **refined axionite**. Accepts input and produces output from any side.

| Property | Value |
|----------|-------|
| HP | 50 |
| Base cost | 120 Ti |
| Scaling | 100% |

> **Warning:** Foundries have the highest scaling contribution at +100% each. Building one adds 100% to your cost multiplier (e.g. 1.0x → 2.0x if it's your first build, but 1.5x → 2.5x if you've already built other things). Plan carefully before committing 120 Ti.

### Refining Process

1. Feed titanium (via conveyor) → foundry stores it
2. Feed raw axionite (via conveyor) → foundry combines them
3. Foundry outputs one stack of refined axionite to an adjacent accepting building
