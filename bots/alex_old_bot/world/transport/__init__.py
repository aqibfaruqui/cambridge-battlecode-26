"""
Conveyor graph algorithm: builds a directed graph of the resource transport
network and supports reachability queries annotated by resource type.

Usage:
    graph = build_conveyor_graph(accumulated_buildings)
    graph.can_reach(harvester_pos, core_pos, ResourceType.TITANIUM)
    graph.reachable_sinks(harvester_pos, ResourceType.TITANIUM)
"""

from __future__ import annotations

from dataclasses import dataclass

from cambc import Direction, EntityType, Environment, Position, ResourceType, Team

from grid import DIRS_CARDINAL, DIRS_OPPOSITE

# Entity types that participate in the conveyor network
CONVEYOR_TYPES = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
}

SPLITTER_TYPE = EntityType.SPLITTER
BRIDGE_TYPE = EntityType.BRIDGE

TURRET_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
}

SINK_TYPES = {EntityType.CORE} | TURRET_TYPES
SOURCE_TYPES = {EntityType.HARVESTER, EntityType.FOUNDRY}

ALL_NETWORK_TYPES = (
    CONVEYOR_TYPES | {SPLITTER_TYPE, BRIDGE_TYPE} | SINK_TYPES | SOURCE_TYPES
)

CARDINAL_SET = set(DIRS_CARDINAL)


@dataclass(frozen=True)
class BuildingInfo:
    """One observed building, stored by the caller in a dict keyed by Position."""

    entity_type: EntityType
    direction: Direction | None = None  # Conveyors, splitters, turrets
    team: Team | None = None  # Cores, turrets
    environment: Environment | None = None  # Harvester: ore underneath
    bridge_target: Position | None = None  # Bridge only


# ---------------------------------------------------------------------------
# Pure-function helpers for directional connectivity
# ---------------------------------------------------------------------------


def _output_positions(
    pos: Position, info: BuildingInfo
) -> list[tuple[Position, Direction]]:
    """Return (output_tile, direction_from_source_to_tile) pairs for a building."""
    etype = info.entity_type

    if etype in (EntityType.HARVESTER, EntityType.FOUNDRY):
        # Output to all 4 cardinal neighbours
        return [(pos.add(d), d) for d in DIRS_CARDINAL]

    if etype in CONVEYOR_TYPES:
        d = info.direction
        assert d is not None
        return [(pos.add(d), d)]

    if etype == SPLITTER_TYPE:
        d = info.direction
        assert d is not None
        back = DIRS_OPPOSITE[d]
        # Splitter outputs in all cardinal directions except the back
        return [(pos.add(out_d), out_d) for out_d in DIRS_CARDINAL if out_d != back]

    if etype == BRIDGE_TYPE:
        target = info.bridge_target
        assert target is not None
        # Direction doesn't matter for bridge output — it bypasses restrictions
        direction_to_target = pos.direction_to(target)
        return [(target, direction_to_target)]

    # Sinks (core, turrets) and launcher don't output resources in the network
    return []


def _accepts_from(info: BuildingInfo, arrival_direction: Direction) -> bool:
    """Check if a building accepts input arriving from `arrival_direction`.

    `arrival_direction` is the direction the resource comes FROM, relative to
    the target building. E.g. if a resource travels eastward into a building,
    the arrival direction is WEST (it arrives from the west side).
    """
    etype = info.entity_type

    if etype in CONVEYOR_TYPES:
        # Accepts from any direction except its output direction
        return arrival_direction != info.direction

    if etype == SPLITTER_TYPE:
        # Only accepts from the back (opposite of facing)
        return arrival_direction == DIRS_OPPOSITE.get(info.direction)

    if etype == BRIDGE_TYPE:
        # Accepts from all cardinal directions
        return arrival_direction in CARDINAL_SET

    if etype == EntityType.CORE:
        # Accepts from any direction
        return True

    if etype == EntityType.FOUNDRY:
        # Accepts from all cardinal directions
        return arrival_direction in CARDINAL_SET

    if etype in TURRET_TYPES:
        if etype == EntityType.LAUNCHER:
            return False  # Launcher doesn't use ammo
        d = info.direction
        if d is None:
            return False
        # Cardinal-facing turrets reject input from their facing direction
        # Diagonal-facing turrets accept from all 4 cardinal sides
        if d in CARDINAL_SET:
            return arrival_direction != d
        return True  # diagonal facing -> all cardinal sides ok

    return False


def _accepts_from_bridge(info: BuildingInfo) -> bool:
    """Bridges bypass directional restrictions — check if entity accepts resources at all."""
    etype = info.entity_type
    if etype == EntityType.LAUNCHER:
        return False
    return etype in ALL_NETWORK_TYPES


def _harvester_resource(env: Environment | None) -> set[ResourceType]:
    if env == Environment.ORE_TITANIUM:
        return {ResourceType.TITANIUM}
    if env == Environment.ORE_AXIONITE:
        return {ResourceType.RAW_AXIONITE}
    return set()
