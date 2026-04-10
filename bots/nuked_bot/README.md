# cs2 Bot

## Entry Point

`main.py` — `Player.run()` dispatches by `EntityType` to `Core` or `Builder` logic objects, which are instantiated once and reused across turns.

## Directory Structure

```
main.py                        # Player dispatcher
entity/
  core.py                      # Core logic: spawns builders via BotReleaseInstruction
  sentinel.py                  # Sentinel turret logic
  builder/
    roles.py                   # BuilderType enum (encodes role as 3x3 grid offset from core)
    __init__.py                 # Builder dispatcher: reads role from markers, routes to behaviour
    behaviour/
      explorer.py              # RANDOM_EXPLORER behaviour
      force_killer.py          # FORCE_KILLER behaviour
action/
  interface.py                 # Action + Behaviour base classes; run_actions() stack runner
  build.py                     # Build-related atomic actions
  combat.py                    # Combat atomic actions
  navigation.py                # Movement atomic actions
  composed/
    goto_place_harvester.py    # Multi-step composed action
world/
  state.py                     # GlobalState: opt-in tracking (core pos, enemy core, conveyor graph)
  sensing.py                   # Sensor helpers
  comms/
    for_builder_bot.py         # Marker-based inter-unit messaging (claim ore, etc.)
  transport/
    flow.py                    # ConveyorGraph construction and querying
nav/
  alex_nav.py                  # Pathfinding
  space_map.py                 # Spatial map utilities
grid.py                        # Grid helpers
```

## Key Patterns

**Action stack (`action/interface.py`)**: Behaviours own a `list[Action]`. Each turn, `run_actions()` executes the top action; on `SUCCESS` it pops and continues, on `FAILURE` it pops and returns, on `INCOMPLETE` it stops. Actions declare a `can_run()` precondition.

**Behaviour lifecycle**: `Behaviour.tick()` calls `check_interrupts()` → `check_transitions()` → `idle()` (if stack empty) → `run_actions()`. Override these hooks per role.

**Builder roles**: `BuilderType` is an `IntEnum` whose value encodes a 3×3 offset from the core position. The core writes a builder's role into a nearby marker; builders read it on spawn to self-identify.

**GlobalState**: Constructed with feature flags (`track_core`, `track_conveyor_graph`, etc.). Call `.update(c)` each turn; only enabled features are computed.

**Comms**: Messages are 32-bit ints packed as `[4b audience][4b type][24b payload]` and XOR-encrypted via `Encrypyt`. `PositionEncoder` packs/unpacks a `Position` into 12 bits.

**Composed actions** (`action/composed/`): Multi-step sequences assembled from atomic actions; prefer composing rather than putting logic in behaviours.
