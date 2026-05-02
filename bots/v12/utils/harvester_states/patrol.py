from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position

from utils.healing import try_heal_nearby_conveyor
from utils.harvester_states.seek import _seek_direction
from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.harvester import Harvester

_PATROL_MAX_TURNS = 80
_MEMORY_CONVEYOR = "conveyor"
_MEMORY_BRIDGE = "bridge"

_REPAIRABLE_TILE_TYPES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.MARKER,
}

_OPPOSITE: dict[Direction, Direction] = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST:  Direction.WEST,
    Direction.WEST:  Direction.EAST,
}


def _passable_near(self: Harvester, pos: Position) -> Position:
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


def _on_map(c: Controller, pos: Position) -> bool:
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def _bridge_target_matches(c: Controller, bridge_id: int, target: Position) -> bool:
    try:
        return c.get_bridge_target(bridge_id) == target
    except Exception:
        return False


def _expected_conveyor_present(c: Controller, pos: Position, direction: Direction) -> bool:
    bid = c.get_tile_building_id(pos)
    return (
        bid is not None
        and c.get_team(bid) == c.get_team()
        and c.get_entity_type(bid) == EntityType.CONVEYOR
        and c.get_direction(bid) == direction
    )


def _expected_bridge_present(c: Controller, pos: Position, target: Position) -> bool:
    bid = c.get_tile_building_id(pos)
    return (
        bid is not None
        and c.get_team(bid) == c.get_team()
        and c.get_entity_type(bid) == EntityType.BRIDGE
        and _bridge_target_matches(c, bid, target)
    )


def _tile_can_be_repaired(c: Controller, pos: Position) -> bool:
    if not _on_map(c, pos) or not c.is_in_vision(pos):
        return False
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return True
    return c.get_entity_type(bid) in _REPAIRABLE_TILE_TYPES


def _missing_patrol_target(self: Harvester, c: Controller) -> tuple[str, int, int] | None:
    candidates: list[tuple[int, str, int, int]] = []

    for (x, y), direction in self.placed_conveyors.items():
        pos = Position(x, y)
        if not _on_map(c, pos) or not c.is_in_vision(pos):
            continue
        if _expected_conveyor_present(c, pos, direction):
            continue
        if _tile_can_be_repaired(c, pos):
            candidates.append((self.current_pos.distance_squared(pos), _MEMORY_CONVEYOR, x, y))

    for (x, y), target_xy in self.placed_bridges.items():
        pos = Position(x, y)
        if not _on_map(c, pos) or not c.is_in_vision(pos):
            continue
        target = Position(target_xy[0], target_xy[1])
        if _expected_bridge_present(c, pos, target):
            continue
        if _tile_can_be_repaired(c, pos):
            candidates.append((self.current_pos.distance_squared(pos), _MEMORY_BRIDGE, x, y))

    if not candidates:
        return None
    candidates.sort()
    _, kind, x, y = candidates[0]
    return (kind, x, y)


def _repair_spec(
    self: Harvester,
    target: tuple[str, int, int],
) -> tuple[str, Position, Direction | Position] | None:
    kind, x, y = target
    key = (x, y)
    pos = Position(x, y)
    if kind == _MEMORY_CONVEYOR:
        direction = self.placed_conveyors.get(key)
        if direction is None:
            return None
        return kind, pos, direction
    if kind == _MEMORY_BRIDGE:
        target_xy = self.placed_bridges.get(key)
        if target_xy is None:
            return None
        return kind, pos, Position(target_xy[0], target_xy[1])
    return None


def _expected_component_present(
    c: Controller,
    kind: str,
    pos: Position,
    extra: Direction | Position,
) -> bool:
    if kind == _MEMORY_CONVEYOR and isinstance(extra, Direction):
        return _expected_conveyor_present(c, pos, extra)
    if kind == _MEMORY_BRIDGE and isinstance(extra, Position):
        return _expected_bridge_present(c, pos, extra)
    return False


def _try_rebuild_component(
    self: Harvester,
    c: Controller,
    kind: str,
    pos: Position,
    extra: Direction | Position,
) -> bool:
    if kind == _MEMORY_CONVEYOR and isinstance(extra, Direction):
        direction = extra
        if c.can_build_conveyor(pos, direction):
            c.build_conveyor(pos, direction)
            self._remember_conveyor(pos, direction)
            return True
    elif kind == _MEMORY_BRIDGE and isinstance(extra, Position):
        target = extra
        if c.can_build_bridge(pos, target):
            c.build_bridge(pos, target)
            self._remember_bridge(pos, target)
            return True
    return _expected_component_present(c, kind, pos, extra)


def _move_toward_repair_target(self: Harvester, c: Controller, pos: Position) -> None:
    self._advance(c, _seek_direction(self, c, pos))


def _handle_patrol_repair(self: Harvester, c: Controller) -> bool:
    if self.patrol_repair_target is None:
        self.patrol_repair_target = _missing_patrol_target(self, c)
        if self.patrol_repair_target is None:
            return False

    spec = _repair_spec(self, self.patrol_repair_target)
    if spec is None:
        self.patrol_repair_target = None
        return False

    kind, pos, extra = spec
    if c.is_in_vision(pos):
        if _expected_component_present(c, kind, pos, extra):
            self.patrol_repair_target = None
            return False
        if not _tile_can_be_repaired(c, pos):
            self.patrol_repair_target = None
            return False

    if not c.is_in_vision(pos):
        _move_toward_repair_target(self, c, pos)
        return True

    bid = c.get_tile_building_id(pos)
    owned = bid is not None and c.get_team(bid) == c.get_team()
    enemy = bid is not None and not owned

    if enemy and self.current_pos != pos:
        _move_toward_repair_target(self, c, pos)
        return True

    if self.current_pos.distance_squared(pos) > 2:
        _move_toward_repair_target(self, c, pos)
        return True

    if owned and c.can_destroy(pos):
        c.destroy(pos)

    if enemy and self.current_pos == pos and c.can_fire(self.current_pos):
        c.fire(self.current_pos)

    if _try_rebuild_component(self, c, kind, pos, extra):
        self.patrol_repair_target = None
    return True


def _patrol_step(self: Harvester, c: Controller, going_out: bool) -> Direction | None:
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
    return _seek_direction(self, c, waypoint)


def _patrol(self: Harvester, c: Controller) -> None:
    self.patrol_turns += 1
    try_heal_nearby_conveyor(c, self.current_pos)

    if _handle_patrol_repair(self, c):
        self.patrol_turns = 0
        return

    if self.patrol_turns > _PATROL_MAX_TURNS:
        self.state = type(self.state).SEEK
        self.patrol_turns = 0
        self.patrol_target = None
        self.patrol_going_out = True
        self.patrol_repair_target = None
        return

    # Flip direction when we reach the end of a leg.
    tip = self.patrol_tip
    at_tip = tip is not None and self.current_pos.distance_squared(tip) <= 2
    inner = self.patrol_inner if self.patrol_inner is not None else self.core_pos
    at_inner = self.current_pos.distance_squared(inner) <= 1
    if (self.patrol_going_out and at_tip) or (not self.patrol_going_out and at_inner):
        self.patrol_going_out = not self.patrol_going_out

    move_dir = _patrol_step(self, c, self.patrol_going_out)
    self._advance(c, move_dir)
