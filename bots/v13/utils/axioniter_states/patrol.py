from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position

from utils.healing import try_heal_nearby_conveyor
from utils.axioniter_states.seek import _idle_rejoin_direction, _seek_direction
from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.axioniter import Axioniter

_PATROL_MAX_TURNS = 80

_OPPOSITE: dict[Direction, Direction] = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}


def _passable_near(self: Axioniter, pos: Position) -> Position:
    """Return a passable tile adjacent to pos (for when pos itself is blocked)."""
    env = self.environment_map
    if env is not None:
        for d in DIRECTIONS_4:
            adj = pos.add(d)
            if env.in_bounds(adj.x, adj.y) and env.is_frontier_passable(adj.x, adj.y):
                return adj
    return pos


def _conveyor_dir_at(c: Controller, pos: Position) -> Direction | None:
    """Return the conveyor direction at pos, or None if not on a conveyor."""
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return None
    if c.get_entity_type(bid) != EntityType.CONVEYOR:
        return None
    return c.get_direction(bid)


def _patrol_step(self: Axioniter, c: Controller, going_out: bool) -> Direction | None:
    """Follow the conveyor chain. Falls back to D* if not on a conveyor."""
    conv_dir = _conveyor_dir_at(c, self.current_pos)
    if conv_dir is not None:
        move_dir = _OPPOSITE.get(conv_dir) if going_out else conv_dir
        if move_dir is not None and c.can_move(move_dir):
            return move_dir
        # Blocked — fall through to D* to navigate around

    # Not on a conveyor — use D*.
    if going_out:
        raw = self.patrol_tip
        waypoint = _passable_near(self, raw) if raw is not None else self.core_pos
    else:
        waypoint = self.patrol_inner if self.patrol_inner is not None else self.core_pos
    return _seek_direction(self, c, waypoint) or _idle_rejoin_direction(self, c)


def _patrol(self: Axioniter, c: Controller) -> None:
    self.patrol_turns += 1
    if self.patrol_turns > _PATROL_MAX_TURNS:
        self.state = type(self.state).SEEK
        self.patrol_turns = 0
        self.patrol_target = None
        self.patrol_going_out = True
        return

    try_heal_nearby_conveyor(c, self.current_pos)

    # Flip direction when we reach the end of a leg.
    tip = self.patrol_tip
    at_tip = tip is not None and self.current_pos.distance_squared(tip) <= 2
    inner = self.patrol_inner if self.patrol_inner is not None else self.core_pos
    at_inner = self.current_pos.distance_squared(inner) <= 1
    if (self.patrol_going_out and at_tip) or (not self.patrol_going_out and at_inner):
        self.patrol_going_out = not self.patrol_going_out

    move_dir = _patrol_step(self, c, self.patrol_going_out)
    self._advance(c, move_dir)
