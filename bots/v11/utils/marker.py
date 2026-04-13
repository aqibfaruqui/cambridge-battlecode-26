"""
32-bit Marker Protocol
[ 8 bits MarkerType ][ 24 bits Payload ]
"""

from cambc import Controller, EntityType, Position
from enum import IntEnum


class MarkerType(IntEnum):
    ROLE_ASSIGN = 1
    # .. add more :D


MARKERTYPE_SHIFT = 24
MARKERTYPE_MASK = 0xFF << MARKERTYPE_SHIFT
PAYLOAD_MASK = 0xFFFFFF


def encode_marker(marker_type: MarkerType, payload: int) -> int:
    return (marker_type << MARKERTYPE_SHIFT) | (payload & PAYLOAD_MASK)


def decode_marker(value: int) -> tuple[int, int]:
    marker_type = value & MARKERTYPE_MASK
    payload = value & PAYLOAD_MASK
    return marker_type, payload


def get_marker_id(c: Controller, pos: Position):
    id = c.get_tile_building_id(pos)
    etype = c.get_entity_type(id)
    if id is not None and etype == EntityType.MARKER:
        return id

    return None


#################
## ROLE_ASSIGN ##
#################
class BuilderRole(IntEnum):
    HARVESTER = 1
    ATTACKER = 2


def encode_role_assign(role: BuilderRole) -> int:
    return encode_marker(MarkerType.ROLE_ASSIGN, role)
