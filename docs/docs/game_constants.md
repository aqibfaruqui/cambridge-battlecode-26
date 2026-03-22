# Game Constants

All numeric constants available via `GameConstants`.
```python
from cambc import GameConstants

max_turns = GameConstants.MAX_TURNS  # 2000
```

---

## General

| Constant | Value | Description |
|---|---|---|
| `MAX_TURNS` | 2000 | Maximum number of turns per game |
| `STACK_SIZE` | 10 | Resources are moved in stacks of 10 |
| `STARTING_TITANIUM` | 1000 | Each team's initial titanium |
| `STARTING_AXIONITE` | 0 | Each team's initial axionite |

---

## Radii (squared)

| Constant | Value | Description |
|---|---|---|
| `ACTION_RADIUS_SQ` | 2 | Default action radius for units |
| `CORE_ACTION_RADIUS_SQ` | 8 | Core action radius (from centre) |
| `CORE_SPAWNING_RADIUS_SQ` | 2 | Core spawning radius |
| `CORE_VISION_RADIUS_SQ` | 36 | Core vision |
| `BUILDER_BOT_VISION_RADIUS_SQ` | 20 | Builder bot vision |
| `GUNNER_VISION_RADIUS_SQ` | 13 | Gunner vision |
| `SENTINEL_VISION_RADIUS_SQ` | 32 | Sentinel vision |
| `BREACH_VISION_RADIUS_SQ` | 10 | Breach vision |
| `BREACH_ATTACK_RADIUS_SQ` | 5 | Breach attack cone |
| `LAUNCHER_VISION_RADIUS_SQ` | 26 | Launcher vision + throw range |
| `BRIDGE_TARGET_RADIUS_SQ` | 9 | Max bridge output distance² |

---

## Base Costs (titanium, axionite)

| Constant | Value |
|---|---|
| `BUILDER_BOT_BASE_COST` | (10, 0) |
| `CONVEYOR_BASE_COST` | (3, 0) |
| `SPLITTER_BASE_COST` | (6, 0) |
| `BRIDGE_BASE_COST` | (10, 0) |
| `ARMOURED_CONVEYOR_BASE_COST` | (10, 5) |
| `HARVESTER_BASE_COST` | (80, 0) |
| `ROAD_BASE_COST` | (1, 0) |
| `BARRIER_BASE_COST` | (3, 0) |
| `FOUNDRY_BASE_COST` | (120, 0) |
| `GUNNER_BASE_COST` | (10, 0) |
| `SENTINEL_BASE_COST` | (15, 0) |
| `BREACH_BASE_COST` | (30, 10) |
| `LAUNCHER_BASE_COST` | (20, 0) |

---

## Max HP

| Constant | Value |
|---|---|
| `CORE_MAX_HP` | 500 |
| `BUILDER_BOT_MAX_HP` | 30 |
| `CONVEYOR_MAX_HP` | 20 |
| `SPLITTER_MAX_HP` | 20 |
| `BRIDGE_MAX_HP` | 20 |
| `ARMOURED_CONVEYOR_MAX_HP` | 50 |
| `HARVESTER_MAX_HP` | 30 |
| `ROAD_MAX_HP` | 10 |
| `BARRIER_MAX_HP` | 30 |
| `FOUNDRY_MAX_HP` | 50 |
| `MARKER_MAX_HP` | 1 |
| `GUNNER_MAX_HP` | 40 |
| `SENTINEL_MAX_HP` | 30 |
| `BREACH_MAX_HP` | 60 |
| `LAUNCHER_MAX_HP` | 30 |

---

## Combat

| Constant | Value | Description |
|---|---|---|
| `BUILDER_BOT_SELF_DESTRUCT_DAMAGE` | 20 | Damage on self-destruct |
| `HEAL_AMOUNT` | 10 | HP restored per heal action |
| `GUNNER_DAMAGE` | 10 | Gunner base damage per shot |
| `GUNNER_FIRE_COOLDOWN` | 1 | Turns between gunner shots |
| `GUNNER_AMMO_COST` | 2 | Resources consumed per shot |
| `SENTINEL_DAMAGE` | 20 | Sentinel damage per shot |
| `SENTINEL_FIRE_COOLDOWN` | 4 | Turns between sentinel shots |
| `SENTINEL_AMMO_COST` | 10 | Resources consumed per shot |
| `BREACH_DAMAGE` | 40 | Breach direct hit damage |
| `BREACH_SPLASH_DAMAGE` | 20 | Breach splash damage |
| `BREACH_FIRE_COOLDOWN` | 1 | Turns between breach shots |
| `BREACH_AMMO_COST` | 5 | Refined axionite per shot |
| `LAUNCHER_FIRE_COOLDOWN` | 1 | Turns between launcher throws |