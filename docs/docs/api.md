# Controller API Reference

The `Controller` object (`c`) is passed to `Player.run()` each round.
```python
class Player:
    def run(self, c: Controller):
        pos = c.get_position()
```

---

## Info Methods

### Unit Info

| Method | Returns | Description |
|--------|---------|-------------|
| `get_team(id: int \| None = None)` | `Team` | Team of the entity with the given id, or this unit if omitted. |
| `get_position(id: int \| None = None)` | `Position` | Position of the entity with the given id, or this unit if omitted. |
| `get_id()` | `int` | This unit's entity id. |
| `get_action_cooldown()` | `int` | This unit's current action cooldown. Actions require cooldown == 0. |
| `get_move_cooldown()` | `int` | This unit's current move cooldown. Movement requires cooldown == 0. |
| `get_hp(id: int \| None = None)` | `int` | Current HP of the entity with the given id, or this unit if omitted. |
| `get_max_hp(id: int \| None = None)` | `int` | Max HP of the entity with the given id, or this unit if omitted. |
| `get_entity_type(id: int \| None = None)` | `EntityType` | EntityType of the entity with the given id, or this unit if omitted. |
| `get_direction(id: int \| None = None)` | `Direction` | Facing direction of a conveyor, splitter, armoured conveyor, or turret. Raises `GameError` if the entity has no direction. |
| `get_vision_radius_sq(id: int \| None = None)` | `int` | Vision radius squared of the given unit, or this unit if omitted. |

### Turret Info

| Method | Returns | Description |
|--------|---------|-------------|
| `get_ammo_amount()` | `int` | Amount of ammo this turret currently holds. |
| `get_ammo_type()` | `ResourceType \| None` | Resource type loaded as ammo, or `None` if empty. |
| `get_gunner_target()` | `Position \| None` | Position of the closest non-empty tile in the gunner's facing direction, or `None` if nothing is in range. Only valid on gunners. |

### Building Info

| Method | Returns | Description |
|--------|---------|-------------|
| `get_bridge_target(id: int)` | `Position` | Output target position of a bridge. Raises `GameError` if not a bridge. |
| `get_stored_resource(id: int \| None = None)` | `ResourceType \| None` | Resource stored in a conveyor/splitter/armoured conveyor/bridge/foundry, or `None` if empty. Raises `GameError` if the entity has no storage. |

### Tile Queries

| Method | Returns | Description |
|--------|---------|-------------|
| `get_tile_env(pos: Position)` | `Environment` | Environment type (empty, wall, ore) of the tile at pos. |
| `get_tile_building_id(pos: Position)` | `int \| None` | ID of the building on the tile at pos, or `None` if empty. |
| `get_tile_builder_bot_id(pos: Position)` | `int \| None` | ID of the builder bot on the tile at pos, or `None` if empty. |
| `is_tile_empty(pos: Position)` | `bool` | `True` if the tile has no building and is not a wall. |
| `is_tile_passable(pos: Position)` | `bool` | `True` if a builder bot belonging to this team could stand on the tile. |
| `is_in_vision(pos: Position)` | `bool` | `True` if pos is within this unit's vision radius. |

### Nearby Queries

| Method | Returns | Description |
|--------|---------|-------------|
| `get_nearby_tiles(dist_sq: int \| None = None)` | `list[Position]` | All in-bounds tile positions within dist_sq (defaults to vision radius). dist_sq must not exceed the vision radius. |
| `get_nearby_entities(dist_sq: int \| None = None)` | `list[int]` | IDs of all entities on tiles within dist_sq (defaults to vision radius). |
| `get_nearby_buildings(dist_sq: int \| None = None)` | `list[int]` | IDs of all buildings within dist_sq (defaults to vision radius). |
| `get_nearby_units(dist_sq: int \| None = None)` | `list[int]` | IDs of all units within dist_sq (defaults to vision radius). |

### Map & Game State

| Method | Returns | Description |
|--------|---------|-------------|
| `get_map_width()` | `int` | Width of the map in tiles. |
| `get_map_height()` | `int` | Height of the map in tiles. |
| `get_current_round()` | `int` | Current round number (starts at 1). |
| `get_global_resources()` | `tuple[int, int]` | `(titanium, axionite)` in this team's global resource pool. |
| `get_scale_percent()` | `float` | This team's current cost scale as a percentage (100.0 = base cost). |
| `get_cpu_time_elapsed()` | `int` | CPU time elapsed this round in microseconds. |

---

## Cost Getters

Every buildable entity has a cost getter returning the current scaled `(titanium, axionite)` cost:
```python
c.get_conveyor_cost()           # -> (int, int)
c.get_splitter_cost()
c.get_bridge_cost()
c.get_armoured_conveyor_cost()
c.get_harvester_cost()
c.get_road_cost()
c.get_barrier_cost()
c.get_gunner_cost()
c.get_sentinel_cost()
c.get_breach_cost()
c.get_launcher_cost()
c.get_foundry_cost()
c.get_builder_bot_cost()
```

---

## Movement

| Method | Returns | Description |
|--------|---------|-------------|
| `move(direction: Direction)` | `None` | Move this builder bot one step in direction. Raises `GameError` if not legal. |
| `can_move(direction: Direction)` | `bool` | `True` if this builder bot can move in direction this round. |

---

## Building

All `build_*` methods require action cooldown == 0 and sufficient resources. `can_build_*` variants return `bool`; `build_*` raises `GameError` if not legal.

### Directional Buildings
Take `(position: Position, direction: Direction)`:
```python
c.build_conveyor(pos, direction)          c.can_build_conveyor(pos, direction)
c.build_splitter(pos, direction)          c.can_build_splitter(pos, direction)
c.build_armoured_conveyor(pos, direction) c.can_build_armoured_conveyor(pos, direction)
c.build_gunner(pos, direction)            c.can_build_gunner(pos, direction)
c.build_sentinel(pos, direction)          c.can_build_sentinel(pos, direction)
c.build_breach(pos, direction)            c.can_build_breach(pos, direction)
```

### Bridge
Takes `(position: Position, target: Position)` — the bridge's output target tile (within distance² 9):
```python
c.build_bridge(pos, target)               c.can_build_bridge(pos, target)
```

### Non-Directional Buildings
Take only `(position: Position)`:
```python
c.build_harvester(pos)                    c.can_build_harvester(pos)
c.build_road(pos)                         c.can_build_road(pos)
c.build_barrier(pos)                      c.can_build_barrier(pos)
c.build_foundry(pos)                      c.can_build_foundry(pos)
c.build_launcher(pos)                     c.can_build_launcher(pos)
```

---

## Healing & Destruction

| Method | Returns | Description |
|--------|---------|-------------|
| `heal(position: Position)` | `None` | Heal all friendly entities on the tile by 10 HP. Costs one action cooldown. |
| `can_heal(position: Position)` | `bool` | `True` if this builder bot can heal the tile this round. |
| `destroy(building_pos: Position)` | `None` | Destroy the allied building at building_pos. Does **not** cost action cooldown. |
| `can_destroy(building_pos: Position)` | `bool` | `True` if this builder bot can destroy the allied building. |
| `self_destruct()` | `None` | Destroy this unit. Builder bots deal 20 damage to their tile. |

---

## Markers

| Method | Returns | Description |
|--------|---------|-------------|
| `place_marker(position: Position, value: int)` | `None` | Place a marker with the given u32 value. Does not cost action cooldown. Max one per round. |
| `can_place_marker(position: Position)` | `bool` | `True` if this unit can place a marker at position this round. |
| `get_marker_value(id: int)` | `int` | The u32 value stored in the friendly marker. |

---

## Combat

| Method | Returns | Description |
|--------|---------|-------------|
| `fire(target: Position)` | `None` | Fire this turret at target. Use `launch()` for launchers. |
| `can_fire(target: Position)` | `bool` | `True` if this turret can fire at target this round. |
| `launch(bot_pos: Position, target: Position)` | `None` | Pick up the builder bot at bot_pos and throw it to target. |
| `can_launch(bot_pos: Position, target: Position)` | `bool` | `True` if this launcher can pick up and throw the bot. |

---

## Core

| Method | Returns | Description |
|--------|---------|-------------|
| `spawn_builder(position: Position)` | `None` | Spawn a builder bot on one of the 9 core tiles. Costs one action cooldown. |
| `can_spawn(position: Position)` | `bool` | `True` if the core can spawn a builder at position this round. |

---

## Debug Indicators

| Method | Returns | Description |
|--------|---------|-------------|
| `draw_indicator_line(pos_a: Position, pos_b: Position, r: int, g: int, b: int)` | `None` | Draw a debug line between two positions with RGB colour. Saved to the replay. |
| `draw_indicator_dot(pos: Position, r: int, g: int, b: int)` | `None` | Draw a debug dot at a position with RGB colour. Saved to the replay. |
