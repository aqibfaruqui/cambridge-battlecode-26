"""
32-bit Marker Protocol
[ 8 bits MarkerType ][ 24 bits Payload ]
"""

from cambc import Controller, EntityType, Position
from enum import IntEnum


class MarkerType(IntEnum):
    ROLE_ASSIGN = 1
    SEEK_CLAIM = 2


MARKERTYPE_SHIFT = 24
MARKERTYPE_MASK = 0xFF << MARKERTYPE_SHIFT
PAYLOAD_MASK = 0xFFFFFF


def encode_marker(marker_type: MarkerType, payload: int) -> int:
    return (marker_type << MARKERTYPE_SHIFT) | (payload & PAYLOAD_MASK)


def decode_marker(value: int) -> tuple[int, int]:
    marker_type = (value >> MARKERTYPE_SHIFT) & 0xFF
    payload = value & PAYLOAD_MASK
    return marker_type, payload


def get_marker_id(c: Controller, pos: Position):
    id = c.get_tile_building_id(pos)
    if id is None:
        return None
    if c.get_entity_type(id) == EntityType.MARKER:
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


##################
## SEEK_CLAIM   ##
## Payload layout: [ 1 bit is_ore ][ 8 bits x ][ 8 bits y ][ 7 bits unused ]
##################

def encode_seek_claim(target: Position, is_ore: bool) -> int:
    payload = (int(is_ore) << 16) | ((target.x & 0xFF) << 8) | (target.y & 0xFF)
    return encode_marker(MarkerType.SEEK_CLAIM, payload)


def decode_seek_claim(value: int) -> tuple[Position, bool]:
    _, payload = decode_marker(value)
    is_ore = bool((payload >> 16) & 1)
    x = (payload >> 8) & 0xFF
    y = payload & 0xFF
    return Position(x, y), is_ore
