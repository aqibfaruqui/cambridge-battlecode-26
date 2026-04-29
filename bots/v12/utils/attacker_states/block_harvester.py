from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position

from utils.attacker_states.state import AttackState
from utils.pathfinding.movement import DIRECTIONS_8, on_map

if TYPE_CHECKING:
    from builders.attacker import Attacker


_CARDINAL = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)


def _enemy_harvester_dir(c: Controller, target: Position, my_team) -> Direction | None:
    """Pick a cardinal direction from `target` toward an in-vision enemy harvester."""
    for d in _CARDINAL:
        adj = target.add(d)
        if not on_map(c, adj) or not c.is_in_vision(adj):
            continue
        bid = c.get_tile_building_id(adj)
        if bid is None:
            continue
        if c.get_entity_type(bid) == EntityType.HARVESTER and c.get_team(bid) != my_team:
            return d
    return None


def _target_still_valid(self: Attacker, c: Controller) -> bool:
    target = self.harvester_block_target
    if target is None:
        return False
    if not c.is_in_vision(target):
        return True
    bid = c.get_tile_building_id(target)
    if bid is not None and c.get_entity_type(bid) != EntityType.MARKER:
        return False
    return _enemy_harvester_dir(c, target, c.get_team()) is not None


def block_harvester(self: Attacker, c: Controller) -> None:
    target = self.harvester_block_target
    assert target is not None

    if not _target_still_valid(self, c):
        self.blacklist[(target.x, target.y)] = c.get_current_round()
        self.harvester_block_target = None
        self._planner_goal = None
        self.state = AttackState.SCAN
        return

    self.target_pos = target
    c.draw_indicator_line(self.current_pos, target, 0, 200, 100)

    me = self.current_pos
    my_team = c.get_team()

    # Standing on the build square — step off so we can build on it.
    if me == target:
        for d in DIRECTIONS_8:
            if c.can_move(d):
                c.move(d)
                return
        return

    # Already 8-adjacent: hold and try to build a gunner here.
    if max(abs(me.x - target.x), abs(me.y - target.y)) == 1:
        if c.get_action_cooldown() == 0:
            facing = _enemy_harvester_dir(c, target, my_team) or me.direction_to(target)
            if facing == Direction.CENTRE:
                facing = Direction.NORTH
            if c.can_build_gunner(target, facing):
                c.build_gunner(target, facing)
                self.harvester_block_target = None
                self._planner_goal = None
                self.state = AttackState.SCAN
        return

    self._search(c, target)
