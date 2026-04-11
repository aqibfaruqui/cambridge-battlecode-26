# Return Flow

This diagram reflects the current return-to-core flow in:

- `bots/v10/builders/harvester_revamped.py`
- `bots/v10/utils/harvester_states/return_to_core.py`

```mermaid
flowchart TD
    A["_return"] --> B["update foundry flag"]
    B --> C{"just placed?"}

    C -->|yes| D["build first connector"]
    D --> E{"connector finished?"}
    E -->|yes| F["just_placed = false"]
    E -->|no| Z["end turn"]

    C -->|no| G{"already in core footprint?"}
    G -->|yes| H["clear target and harvester"]
    H --> I["reset return state"]
    I --> J["switch to SEEK"]
    G -->|no| K{"pending bridge?"}

    K -->|yes| L["handle pending bridge"]
    L --> Z

    K -->|no| M{"post bridge conveyor?"}
    M -->|yes| N["repair landing tile into inward conveyor"]
    N --> Z

    M -->|no| O["build return step"]

    O --> P{"return_actions empty?"}
    P -->|yes| Q["get 8-way intent to core"]
    P -->|no| Y["use committed action queue"]

    Q --> R{"intent cardinal?"}
    R -->|yes| S["queue one cardinal action"]
    R -->|no| T["try diagonal split"]

    T --> U{"full 2-step split committable?"}
    U -->|yes| V["queue committed split"]
    U -->|no| W["do diagonal road plus bridge fallback"]

    S --> Y
    V --> Y
    W --> X["clear actions, road diagonal landing if possible, move diagonal, set bridge_from"]
    X --> Z

    Y --> AA["take first queued move"]
    AA --> AB["compute next conveyor direction"]
    AB --> AC{"step executable now?"}

    AC -->|yes| AD["continue"]
    AC -->|no| AE["plan blocked step fallback"]

    AE --> AF{"blocked move diagonal?"}
    AF -->|yes| AG["retry split or bridge"]
    AF -->|no| AH{"direct diagonal bridge toward core?"}
    AH -->|yes| AI["bridge fast"]
    AH -->|no| AJ["clear queued actions and fail turn"]

    AG --> AK{"fallback split works?"}
    AK -->|yes| AL["replace action queue"]
    AK -->|no| AM["use bridge fallback"]

    AI --> AM
    AL --> AD
    AM --> X

    AD --> AN{"next tile reaches core?"}
    AN -->|yes| AO{"can move?"}
    AO -->|yes| AP["pop action and move into core"]
    AO -->|no| AJ

    AN -->|no| AQ{"next tile is core building?"}
    AQ -->|yes| AO
    AQ -->|no| AR["clear return tile if needed"]

    AR --> AS{"tile usable after clear?"}
    AS -->|no| AJ
    AS -->|yes| AT{"can build conveyor?"}
    AT -->|yes| AU["build conveyor"]
    AT -->|no| AV["skip build"]

    AU --> AW{"can move?"}
    AV --> AW
    AW -->|yes| AX["pop action and move"]
    AW -->|no| AJ

    L --> BA["clear friendly road or conveyor on bridge origin if needed"]
    BA --> BB{"can build bridge from origin to current?"}
    BB -->|yes| BC["build bridge"]
    BC --> BD["clear bridge_from and mark post_bridge_conveyor"]
    BB -->|no| Z
    BD --> Z

    N --> BE{"already in core?"}
    BE -->|yes| BF["clear post_bridge_conveyor"]
    BE -->|no| BG["get inward 4-way conveyor direction"]
    BG --> BH["clear current tile if needed"]
    BH --> BI{"tile empty and can build conveyor?"}
    BI -->|yes| BJ["build landing conveyor"]
    BI -->|no| BK["skip build"]
    BJ --> BL["clear post_bridge_conveyor"]
    BK --> BL

    F --> Z
    J --> Z
    AP --> Z
    AX --> Z
    AJ --> Z
    BF --> Z
    BL --> Z
```

## Key Rules

- Return uses 8-way intent, but actual transport is committed as cardinal actions.
- A diagonal split is only allowed if both cardinal components are committable up front.
- If a diagonal cannot be safely split, it falls back to diagonal move plus next-turn bridge.
- If a committed step is blocked, return prefers a bridge-oriented fallback instead of broad rerouting.
- After a bridge is built, the landing tile is repaired into an inward conveyor before normal return continues.
