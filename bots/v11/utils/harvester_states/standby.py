from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position

from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.harvester import Harvester


_WALKABLE_INFRA = (
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
    EntityType.BRIDGE,
    EntityType.ROAD,
    EntityType.CORE,
)

_CONVEYOR_TYPES = (
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
)


def _is_friendly_walkable(c: Controller, pos: Position) -> bool:
    if not c.is_in_vision(pos):
        return False
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return False
    if c.get_team(bid) != c.get_team():
        return False
    return c.get_entity_type(bid) in _WALKABLE_INFRA


def _standby(self: Harvester, c: Controller) -> None:
    pos = self.current_pos

    # Prefer following the conveyor arrow under our feet — keeps the bot
    # drifting along the network toward core instead of oscillating.
    bid = c.get_tile_building_id(pos)
    if bid is not None and c.get_team(bid) == c.get_team():
        etype = c.get_entity_type(bid)
        if etype in _CONVEYOR_TYPES:
            move_dir = c.get_direction(bid)
            target = pos.add(move_dir)
            if _is_friendly_walkable(c, target) and c.can_move(move_dir):
                self.standby_prev_pos = pos
                c.move(move_dir)
                return

    # Otherwise, pick any adjacent friendly walkable tile, avoiding the
    # tile we just came from so we don't ping-pong.
    fallback = None
    for d in DIRECTIONS_4:
        target = pos.add(d)
        if not _is_friendly_walkable(c, target):
            continue
        if not c.can_move(d):
            continue
        if target == self.standby_prev_pos:
            fallback = d
            continue
        self.standby_prev_pos = pos
        c.move(d)
        return

    if fallback is not None:
        self.standby_prev_pos = pos
        c.move(fallback)
