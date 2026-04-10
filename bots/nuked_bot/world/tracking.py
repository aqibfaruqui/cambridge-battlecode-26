from typing import Optional

from cambc import Controller, EntityType, Position


def find_core_pos(
    c: Controller, current: Optional[Position] = None
) -> Optional[Position]:
    """Scan nearby buildings for our core. Returns current if already known."""
    if current is not None:
        return current

    for bid in c.get_nearby_buildings():
        if c.get_entity_type(bid) == EntityType.CORE and c.get_team(bid) == c.get_team():
            return c.get_position(bid)

    return None
