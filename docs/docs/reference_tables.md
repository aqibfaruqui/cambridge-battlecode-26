# Reference Tables

Quick-reference stat tables for all entities.

---

## Entity Stats

| Entity | HP | Cost | Scale | Notes |
|--------|-----|------|-------|-------|
| Core | 500 | — | — | 3×3; spawns builders |
| Builder bot | 30 | 10 Ti | 10% | Mobile; build, heal, destroy |
| Conveyor | 20 | 3 Ti | 1% | 3 inputs, 1 output |
| Splitter | 20 | 6 Ti | 1% | 1 input, 3 rotating outputs |
| Bridge | 20 | 10 Ti | 1% | Output to tile within dist 3 |
| Armoured conv. | 50 | 10 Ti, 5 Ax | 1% | Conveyor with more HP |
| Harvester | 30 | 80 Ti | 10% | Outputs every 4 rounds |
| Foundry | 50 | 120 Ti | 100% | Ti + raw Ax → refined Ax |
| Road | 10 | 1 Ti | 0.5% | Walkable |
| Barrier | 30 | 3 Ti | 1% | Blocks space |
| Marker | 1 | Free | — | No action cooldown |
| Gunner | 40 | 10 Ti | 10% | Closest tile in facing dir |
| Sentinel | 30 | 15 Ti | 10% | Line ±1; Ax stuns +3 cd |
| Breach | 60 | 30 Ti, 10 Ax | 10% | 180° cone; friendly fire |
| Launcher | 30 | 20 Ti | 10% | Throws adjacent builders |

---

## Unit Combat Stats

| Unit | Vision r² | Action r² | Attack r² | Damage | Reload | Ammo/shot |
|------|-----------|-----------|-----------|--------|--------|-----------|
| Core | 36 | 8 | — | — | — | — |
| Builder bot | 20 | 2 | — | 20 (self-destruct) | — | — |
| Gunner | 13 | 2 | 13 | 10 (+10 with Ax) | 1 | 2 |
| Sentinel | 32 | 2 | 32 | 20 | 4 | 10 |
| Breach | 10 | 2 | 5 | 40 + 20 splash | 1 | 5 |
| Launcher | 26 | 2 (pickup) | 26 (throw) | — | 1 | — |

---

## Game Constants

| Constant | Value |
|----------|-------|
| Max rounds | 2000 |
| Stack size | 10 |
| Starting titanium | 1000 |
| Starting axionite | 0 |
| Builder bot heal | 10 HP |
| Builder bot self-destruct damage | 20 |
| Harvester output interval | Every 4 rounds |
| Sentinel stun (refined axionite ammo) | +3 action and move cooldown |
| CPU time per unit per round | 2ms (+5% buffer) |

---

## Cost Scaling

Every entity you build increases the cost multiplier. Scale starts at 1.0x.

| Entity | Scale Increase |
|--------|---------------|
| Road | +0.5% |
| Conveyor, splitter, armoured conveyor, bridge, barrier | +1% |
| Builder bot, harvester, gunner, sentinel, breach, launcher | +10% |
| Axionite foundry | +100% |
```
cost = floor(scale × base cost)
```
