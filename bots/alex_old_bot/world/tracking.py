from typing import Optional

from cambc import Controller, EntityType, Position
from world.comms.for_buildings import BuildingMessages, BuildingMessageType


def find_core_pos(
    c: Controller, current: Optional[Position] = None
) -> Optional[Position]:
    """Scan nearby buildings/markers for our core. Returns current if already known."""
    if current is not None:
        return current

    for bid in c.get_nearby_buildings():
        if c.get_entity_type(bid) == EntityType.CORE:
            return c.get_position(bid)

    for m in c.get_nearby_buildings():
        if (
            c.get_team(m) == c.get_team()
            and c.get_entity_type(m) == EntityType.MARKER
            and BuildingMessages.is_building_message(c.get_marker_value(m))
            and BuildingMessages.get_message_type(c.get_marker_value(m))
            == BuildingMessageType.SELF_CORE_LOCATION
        ):
            return BuildingMessages.decode_self_core_location(c.get_marker_value(m))

    return None


def find_enemy_core_pos(
    c: Controller, current: Optional[Position] = None
) -> Optional[Position]:
    """Scan nearby buildings/markers for enemy core. Returns current if already known."""
    if current is not None:
        return current

    for bid in c.get_nearby_buildings():
        if (
            c.get_entity_type(bid) == EntityType.CORE
            and c.get_team(bid) != c.get_team()
        ):
            return c.get_position(bid)

    for m in c.get_nearby_buildings():
        if (
            c.get_team(m) == c.get_team()
            and c.get_entity_type(m) == EntityType.MARKER
            and BuildingMessages.is_building_message(c.get_marker_value(m))
            and BuildingMessages.get_message_type(c.get_marker_value(m))
            == BuildingMessageType.ENEMY_CORE_LOCATION
        ):
            return BuildingMessages.decode_enemy_core_location(c.get_marker_value(m))

    return None
