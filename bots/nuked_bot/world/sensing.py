from cambc import Controller, EntityType


def can_afford(
    c: Controller, entity_type: EntityType, *, ti_offset: int = 0, ax_offset: int = 0
) -> bool:
    ti, ax = c.get_global_resources()
    ti -= ti_offset
    ax -= ax_offset
    match entity_type:
        case EntityType.HARVESTER:
            cost = c.get_harvester_cost()
        case EntityType.BUILDER_BOT:
            cost = c.get_builder_bot_cost()
        case EntityType.BRIDGE:
            cost = c.get_bridge_cost()
        case EntityType.CONVEYOR:
            cost = c.get_conveyor_cost()
        case EntityType.SPLITTER:
            cost = c.get_splitter_cost()
        case EntityType.FOUNDRY:
            cost = c.get_foundry_cost()
        case EntityType.GUNNER:
            cost = c.get_gunner_cost()
        case EntityType.LAUNCHER:
            cost = c.get_launcher_cost()
        case EntityType.BREACH:
            cost = c.get_breach_cost()
        case EntityType.ARMOURED_CONVEYOR:
            cost = c.get_armoured_conveyor_cost()
        case EntityType.SENTINEL:
            cost = c.get_sentinel_cost()
        case EntityType.BARRIER:
            cost = c.get_barrier_cost()
        case EntityType.ROAD:
            cost = c.get_road_cost()
        case EntityType.CORE:
            raise ValueError("No price for core. Why are you trying to build one?")
        case _:
            raise ValueError(f"Unknown entity type: {entity_type}")
    return ti >= cost[0] and ax >= cost[1]
