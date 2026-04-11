# Harvester Flow

This diagram reflects the current `v10` harvester flow across:

- `bots/v10/builders/harvester_revamped.py`
- `bots/v10/utils/harvester_states/seek.py`
- `bots/v10/utils/harvester_states/return_to_core.py`

```mermaid
flowchart TD
    A[run] --> B[Update position/resources/memory]
    B --> C{state}

    C -->|SEEK| S0[_seek]
    C -->|RETURN| R0[_return]

    S0 --> S1[Update foundry flag]
    S1 --> S2{Adjacent valid titanium harvester spot?}
    S2 -->|Yes| S3[Clear road if needed]
    S3 --> S4{can_build_harvester?}
    S4 -->|Yes| S5[Build harvester]
    S5 --> S6[Set harvester_pos<br/>just_placed = true<br/>reset return state]
    S6 --> S7[Switch to RETURN]
    S4 -->|No| S8[Keep seeking]
    S2 -->|No| S8

    S8 --> S9[Pick seek target]
    S9 --> S10{Known titanium?}
    S10 -->|Yes| S11[Use known titanium]
    S10 -->|No| S12{Predicted titanium from symmetry?}
    S12 -->|Yes| S13[Use predicted titanium]
    S12 -->|No| S14{Frontier available?}
    S14 -->|Yes| S15[Use frontier target]
    S14 -->|No| S16[Fallback edge target or random 4-way]

    S11 --> S17{Ore target?}
    S13 --> S17
    S15 --> S18[Pathfind directly to target]
    S16 --> S18

    S17 -->|Yes| S19{Ore still valid in vision?}
    S19 -->|No| S20[Blacklist ore and clear target]
    S19 -->|Yes| S21[Pick best adjacent build tile]
    S21 --> S22{Approach tile exists?}
    S22 -->|No| S20
    S22 -->|Yes| S18
    S17 -->|No| S18

    S18 --> S23{Pathfinder found move?}
    S23 -->|No| S24[Clear target]
    S23 -->|Yes| S25[Advance and build road on stepped tile if possible]

    R0 --> R1[Update foundry flag]
    R1 --> R2{just_placed?}
    R2 -->|Yes| R3[Build first connector]
    R3 --> R4{Connector complete?}
    R4 -->|Yes| R5[just_placed = false]
    R4 -->|No| RZ[End turn]
    R2 -->|No| R6{Already in core footprint?}
    R6 -->|Yes| R7[Clear target/harvester<br/>reset return state<br/>switch to SEEK]
    R6 -->|No| R8{Pending bridge?}
    R8 -->|Yes| R9[Handle pending bridge]
    R9 --> RZ
    R8 -->|No| R10{Post-bridge conveyor pending?}
    R10 -->|Yes| R11[Repair landing tile into inward conveyor]
    R11 --> RZ
    R10 -->|No| R12[Build return step]

    R12 --> R13{return_actions empty?}
    R13 -->|Yes| R14[Get 8-way intent toward core]
    R14 --> R15{Intent cardinal?}
    R15 -->|Yes| R16[return_actions = one cardinal step]
    R15 -->|No| R17[Try diagonal split]
    R17 --> R18{Both cardinal components committable?}
    R18 -->|Yes| R19[return_actions = committed split]
    R18 -->|No| R20[Fallback to diagonal road+bridge]

    R16 --> R21[Take first committed step]
    R19 --> R21
    R20 --> R30[Handle diagonal step]

    R21 --> R22[Compute next_move_dir from committed actions or 4-way core hint]
    R22 --> R23{Can execute return step?}
    R23 -->|Yes| R24[Continue]
    R23 -->|No| R25[Plan blocked-step fallback]

    R25 --> R26{Blocked move diagonal?}
    R26 -->|Yes| R27[Retry split or bridge]
    R26 -->|No| R28{Direct diagonal-to-core bridge available?}
    R28 -->|Yes| R29[Bridge fast]
    R28 -->|No| R31[Fail cleanly for turn]

    R24 --> R32{Next tile reaches core?}
    R32 -->|Yes| R33{can_move?}
    R33 -->|Yes| R34[Move into core]
    R33 -->|No| R31

    R32 -->|No| R35{Next tile is core building?}
    R35 -->|Yes| R33
    R35 -->|No| R36[Clear return tile if needed]
    R36 --> R37{Tile clearable/usable?}
    R37 -->|No| R31
    R37 -->|Yes| R38{can_build_conveyor?}
    R38 -->|Yes| R39[Build conveyor]
    R38 -->|No| R40[Skip build]
    R39 --> R41{can_move?}
    R40 --> R41
    R41 -->|Yes| R42[Pop first action and move]
    R41 -->|No| R43[Clear return_actions and fail turn]

    R30 --> R44[Clear return_actions]
    R44 --> R45{Landing tile empty and road placeable?}
    R45 -->|Yes| R46[Build road on diagonal landing tile]
    R45 -->|No| R47[Skip road]
    R46 --> R48{can_move diagonal?}
    R47 --> R48
    R48 -->|Yes| R49[Set bridge_from and move diagonally]
    R48 -->|No| R31

    R9 --> R50[Clear friendly road/conveyor on bridge origin if needed]
    R50 --> R51{can_build_bridge(origin,current)?}
    R51 -->|Yes| R52[Build bridge]
    R52 --> R53[bridge_from = None<br/>post_bridge_conveyor = true]
    R51 -->|No| R31

    R11 --> R54{Already in core?}
    R54 -->|Yes| R55[Clear post_bridge_conveyor]
    R54 -->|No| R56[Get inward 4-way conveyor dir]
    R56 --> R57{Current tile clearable?}
    R57 -->|No| R31
    R57 -->|Yes| R58{Tile empty and can_build_conveyor?}
    R58 -->|Yes| R59[Build landing conveyor]
    R58 -->|No| R60[Skip build]
    R59 --> R61[Clear post_bridge_conveyor]
    R60 --> R61

    R31 --> RZ
    R34 --> RZ
    R42 --> RZ
    R49 --> RZ
    R53 --> RZ
    R55 --> RZ
    R61 --> RZ
    R20 --> RZ
    S7 --> RZ
    S20 --> RZ
    S24 --> RZ
    S25 --> RZ

    RZ[Turn ends]
```

## Notes

- `SEEK` is still mostly planner-driven through `Pathfinding.next_direction(...)`.
- `RETURN` is executor-heavy:
  - 8-way intent
  - committed cardinal splits for diagonals
  - bridge fallback
  - post-bridge conveyor repair
- Diagonals only split when the whole 2-cardinal sequence is committable up front.
- Axionite is treated as passable/placeable when the engine allows conveyor placement.
- A blocked cardinal return step does not do broad rerouting; it prefers a diagonal bridge fallback and otherwise fails cleanly for the turn.
