
from __future__ import annotations
from enum import Enum, auto
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, Controller

from utils.d_star import DStarLite, _RETURN_BLOCK_MASK
from utils.map_memory import CORE_OWN, ORE_AX, TRAVERSABLE, UNKNOWN
from utils.movement import (
    DIRECTIONS_4,
    get_direction_4,
    is_diagonal,
    on_map,
    reached_core,
    split_diagonal,
)
from utils.network_connectivity import compute_reachable_to_core

if TYPE_CHECKING:
    from builders.harvester_revamped import Harvester


class _DiagonalKind(Enum):
    NONE = auto()
    SPLIT = auto()
    BRIDGE_NOW = auto()


_MAX_BRIDGE_FAILS = 3


def _mark_network_reach_dirty(self: Harvester) -> None:
    self.network_reach_dirty = True


def _reachable_to_core(self: Harvester, c) -> set[tuple[int, int]]:
    current_round = c.get_current_round()
    if (
        self.reachable_to_core is None
        or self.network_reach_dirty
        or self.network_reach_round != current_round
    ):
        self.reachable_to_core = compute_reachable_to_core(c, self.core_pos)
        self.network_reach_round = current_round
        self.network_reach_dirty = False
    return self.reachable_to_core


def _receiver_accepts_from(self: Harvester, c, source_pos: Position, receiver_pos: Position, receiver_id: int) -> bool:
    if c.get_team(receiver_id) != c.get_team():
        return False

    entity_type = c.get_entity_type(receiver_id)
    if entity_type == EntityType.CORE:
        return True

    if entity_type == EntityType.BRIDGE:
        return True

    if entity_type in (EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR):
        out_dir = c.get_direction(receiver_id)
        return receiver_pos.add(out_dir) != source_pos

    if entity_type == EntityType.SPLITTER:
        out_dir = c.get_direction(receiver_id)
        return receiver_pos.add(out_dir.opposite()) == source_pos

    return False


def _harvester_attached_to_core(self: Harvester, c) -> bool:
    if self.harvester_pos is None:
        return False

    reachable_to_core = _reachable_to_core(self, c)

    for step_dir in DIRECTIONS_4:
        receiver_pos = self.harvester_pos.add(step_dir)
        if not c.is_in_vision(receiver_pos):
            continue

        if (receiver_pos.x, receiver_pos.y) not in reachable_to_core:
            continue

        receiver_id = c.get_tile_building_id(receiver_pos)
        if receiver_id is None:
            continue

        if _receiver_accepts_from(self, c, self.harvester_pos, receiver_pos, receiver_id):
            return True

    return False



def _reset_return_state(self: Harvester):
    self.bridge_from = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}
    self.shortcut_target = None


def _return_dynamic_blockers(c: Controller) -> list[tuple[int, int]]:
    blockers: list[tuple[int, int]] = []
    team = c.get_team()
    for pos in c.get_nearby_tiles():
        build_id = c.get_tile_building_id(pos)
        if build_id is None:
            continue
        entity_type = c.get_entity_type(build_id)
        owner = c.get_team(build_id)
        if entity_type == EntityType.HARVESTER:
            blockers.append((pos.x, pos.y))
            continue
        if owner != team:
            blockers.append((pos.x, pos.y))
    return blockers

def _ensure_return_planner(self: Harvester, c):
    planner = self.return_planner
    if planner is None and self.environment_map is not None:
        planner = DStarLite(
            self.environment_map,
            self.core_pos.x,
            self.core_pos.y,
            block_mask=_RETURN_BLOCK_MASK,
        )
        self.return_planner = planner
    if planner is not None:
        planner.set_dynamic_blockers(_return_dynamic_blockers(c))
        planner.notify_map_changes()
    return planner


def _refresh_return_planner(self: Harvester, c: Controller) -> tuple[Direction | None, list[tuple[int, int]]]:
    planner = _ensure_return_planner(self, c)
    if planner is None:
        return None, []
    planner.set_position(self.current_pos.x, self.current_pos.y)
    step = planner.step()
    path = planner.extract_path()

    return step, path


def _planner_step_at(self: Harvester, c: Controller, pos: Position) -> Direction | None:
    planner = _ensure_return_planner(self, c)
    if planner is None:
        return None
    planner.set_position(pos.x, pos.y)
    step = planner.step()
    if step == Direction.CENTRE:
        return None
    return step


def _ordered_split(self: Harvester, origin: Position, move_dir: Direction) -> list[Direction] | None:
    ns, ew = split_diagonal(origin, origin.add(move_dir))
    if ns is None or ew is None:
        return None
    preferred = get_direction_4(origin, self.core_pos)
    if preferred == ew:
        return [ew, ns]
    return [ns, ew]


def _resolve_diagonal_plan(
    self: Harvester,
    c: Controller,
    origin: Position,
    move_dir: Direction,
) -> tuple[_DiagonalKind, list[Direction] | None, Direction | None]:
    ordered = _ordered_split(self, origin, move_dir)
    if ordered is None:
        return _DiagonalKind.NONE, None, None

    for first, second in [(ordered[0], ordered[1]), (ordered[1], ordered[0])]:
        first_pos = origin.add(first)
        if not _is_return_tile_usable(self, c, first_pos):
            continue
        if reached_core(first_pos, self.core_pos):
            return _DiagonalKind.SPLIT, [first], None
        if _is_return_tile_usable(self, c, first_pos.add(second)):
            return _DiagonalKind.SPLIT, [first, second], None

    if origin == self.current_pos:
        diag_pos = origin.add(move_dir)
        can_reach = c.can_move(move_dir) or (
            c.get_tile_env(diag_pos) == Environment.EMPTY and c.can_build_road(diag_pos)
        )
        if can_reach:
            return _DiagonalKind.BRIDGE_NOW, None, move_dir

    return _DiagonalKind.NONE, None, None


def _next_dir_after_move(
    self: Harvester,
    c: Controller,
    move_dir: Direction,
    planner_path: list[tuple[int, int]],
) -> Direction | None:
    """Return the conveyor direction to place on the tile we're about to step onto."""
    move_pos = self.current_pos.add(move_dir)

    follow_dir = None
    if len(planner_path) >= 3:
        p0, p1, p2 = planner_path[0], planner_path[1], planner_path[2]
        if p0 == (self.current_pos.x, self.current_pos.y) and p1 == (move_pos.x, move_pos.y):
            follow_dir = move_pos.direction_to(Position(p2[0], p2[1]))

    if follow_dir is None:
        follow_dir = _planner_step_at(self, c, move_pos)
    if follow_dir is None:
        follow_dir = move_pos.direction_to(self.core_pos)
    if follow_dir is None or follow_dir == Direction.CENTRE:
        return None

    if follow_dir in DIRECTIONS_4:
        return follow_dir

    _, split, _ = _resolve_diagonal_plan(self, c, move_pos, follow_dir)
    return split[0] if split else None




def _is_return_tile_usable(self: Harvester, c: Controller, pos: Position) -> bool:
    if reached_core(pos, self.core_pos):
        return True

    if not c.is_in_vision(pos):
        if not on_map(c, pos):
            return False
        
        if self.memory._tiles is None:
            raise ValueError("Expected memory._tiles to be set")
        
        return self.memory._tiles[pos.y][pos.x] in (TRAVERSABLE, ORE_AX, CORE_OWN, UNKNOWN)

    if c.get_tile_env(pos) == Environment.WALL:
        return False

    occupier = c.get_tile_builder_bot_id(pos)
    if occupier is not None and occupier != c.get_id():
        return False

    build_id = c.get_tile_building_id(pos)
    if build_id is None:
        return True

    entity_type = c.get_entity_type(build_id)
    if entity_type == EntityType.ROAD:
        return True
    if entity_type == EntityType.CORE:
        return True
    if c.get_team(build_id) != c.get_team():
        return False
    return entity_type in (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER)


def _clear_return_tile(_: Harvester, c: Controller, pos: Position) -> bool:
    build_id = c.get_tile_building_id(pos)
    if build_id is None:
        return True

    entity_type = c.get_entity_type(build_id)
    if entity_type == EntityType.ROAD:
        if c.can_destroy(pos):
            c.destroy(pos)
            return True
        return False
    if entity_type == EntityType.CORE:
        return True
    if c.get_team(build_id) != c.get_team():
        return False

    if entity_type in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE):
        return True

    return False


def _can_execute_return_step(self: Harvester, c: Controller, move_dir: Direction, next_move_dir: Direction | None) -> bool:
    if c.can_move(move_dir):
        return True

    move_pos = self.current_pos.add(move_dir)
    if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
        return True

    if next_move_dir is None:
        return False

    return c.can_build_conveyor(move_pos, next_move_dir)


def _build_first_connector(self: Harvester, c: Controller) -> bool:
    move_pos = self.current_pos

    # If the harvester was diagonal, pick one of the two cardinal join tiles.
    if self.harvester_pos and is_diagonal(self.current_pos, self.harvester_pos):
        ns, ew = split_diagonal(self.current_pos, self.harvester_pos)
        m1 = self.current_pos.add(ns) # type: ignore
        m2 = self.current_pos.add(ew) # type: ignore
        move_pos = (
            m1
            if m1.distance_squared(self.core_pos) < m2.distance_squared(self.core_pos)
            else m2
        )

    build_id = c.get_tile_building_id(move_pos)
    if build_id is not None and c.get_entity_type(build_id) == EntityType.ROAD and c.can_destroy(move_pos):
        c.destroy(move_pos)

    step = _planner_step_at(self, c, move_pos)
    if step is None:
        step = move_pos.direction_to(self.core_pos)
    if step is None or step == Direction.CENTRE:
        return False
    if step not in DIRECTIONS_4:
        kind, split, bridge_dir = _resolve_diagonal_plan(self, c, move_pos, step)
        if kind == _DiagonalKind.BRIDGE_NOW and bridge_dir is not None:
            return _handle_return_diagonal_step(self, c, bridge_dir)
        if not split:
            return False
        step = split[0]
    conveyor_dir = step

    if c.get_tile_building_id(move_pos) is None:
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if self.ti < conveyor_cost_ti:
            return False
    if c.can_build_conveyor(move_pos, conveyor_dir):
        c.build_conveyor(move_pos, conveyor_dir)
        _mark_network_reach_dirty(self)

    if self.current_pos != move_pos:
        step_dir = get_direction_4(self.current_pos, move_pos)
        if c.can_move(step_dir):
            c.move(step_dir)
            return True
        return False
    return True


def _build_return_step(self: Harvester, c: Controller) -> bool:
    planner_step, planner_path = _refresh_return_planner(self, c)
    carry_next: Direction | None = None

    shortcut = _shortcut_path(planner_path)
    if shortcut is not None:
        x1, y1 = shortcut[1][0]
        start = Position(x1, y1)
        x2, y2 = shortcut[1][1]
        end = Position(x2, y2)

        build_id = c.get_tile_building_id(start)
        entity_type = (
            c.get_entity_type(build_id) if build_id is not None else None
        )
        already_friendly_bridge = (
            build_id is not None
            and entity_type == EntityType.BRIDGE
            and c.get_team(build_id) == c.get_team()
        )

        if not already_friendly_bridge:
            # Only clear a road — keep any friendly conveyor/splitter/bridge
            # in place; if `can_build_bridge` is False afterwards we bail out
            # rather than destroying logistics we already paid for.
            if (
                entity_type == EntityType.ROAD
                and build_id is not None
                and c.get_team(build_id) == c.get_team()
                and c.can_destroy(start)
            ):
                c.destroy(start)
                _mark_network_reach_dirty(self)
            if not c.can_build_bridge(start, end):
                return False
            c.build_bridge(start, end)
            _mark_network_reach_dirty(self)

        # Hand the walk phase over to `_handle_shortcut_walk`, dispatched from
        # `_return` each subsequent tick until we reach `end`. No more bridge
        # building happens during the walk — just move + pave-road-if-stuck.
        self.shortcut_target = end
        _step_to_shortcut_target(self, c)
        return True

    # Determine move_dir — consume carry-forward from previous split, or plan fresh.
    if self.return_next_dir is not None:
        move_dir = self.return_next_dir
        self.return_next_dir = None
    else:
        move_dir = planner_step
        if move_dir is None or move_dir == Direction.CENTRE:
            move_dir = self.current_pos.direction_to(self.core_pos)
        if move_dir is None or move_dir == Direction.CENTRE:
            return False

        if move_dir not in DIRECTIONS_4:
            kind, split, bridge_dir = _resolve_diagonal_plan(self, c, self.current_pos, move_dir)
            if kind == _DiagonalKind.BRIDGE_NOW and bridge_dir is not None:
                return _handle_return_diagonal_step(self, c, bridge_dir)
            if kind == _DiagonalKind.SPLIT and split:
                move_dir = split[0]
                carry_next = split[1] if len(split) > 1 else None
            else:
                return False

    next_dir = _next_dir_after_move(self, c, move_dir, planner_path)
    if carry_next is not None:
        next_dir = carry_next  # split's second step is more reliable than lookahead

    move_pos = self.current_pos.add(move_dir)

    # Core entry — just move, no conveyor needed.
    build_id = c.get_tile_building_id(move_pos)
    if reached_core(move_pos, self.core_pos) or (
        build_id is not None and c.get_entity_type(build_id) == EntityType.CORE
    ):
        if not c.can_move(move_dir):
            return False
        c.move(move_dir)
        return True

    # Normal cardinal step: clear tile, place conveyor (or road for empty tiles), move.
    if not _can_execute_return_step(self, c, move_dir, next_dir):
        return False
    if not _clear_return_tile(self, c, move_pos):
        return False
    dest_empty = c.get_tile_env(move_pos) == Environment.EMPTY
    if next_dir is not None:
        if dest_empty:
            conveyor_cost_ti, _ = c.get_conveyor_cost()
            if self.ti < conveyor_cost_ti:
                return False
        if c.can_build_conveyor(move_pos, next_dir):
            c.build_conveyor(move_pos, next_dir)
            _mark_network_reach_dirty(self)
    elif dest_empty and c.can_build_road(move_pos):
        c.build_road(move_pos)
    if not c.can_move(move_dir):
        return False
    self.return_next_dir = carry_next
    c.move(move_dir)
    return True


def _handle_return_diagonal_step(self: Harvester, c: Controller, move_dir: Direction) -> bool:
    move_pos = self.current_pos.add(move_dir)
    self.return_next_dir = None

    if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if c.can_move(move_dir):
        self.bridge_from = self.current_pos
        c.move(move_dir)
        return True

    return False


def _handle_pending_return_bridge(self: Harvester, c: Controller) -> bool:
    if self.bridge_from is None:
        return False

    bridge_pos = self.bridge_from
    build_id = c.get_tile_building_id(bridge_pos)
    entity_type = c.get_entity_type(build_id) if build_id is not None else None
    key = (bridge_pos.x, bridge_pos.y, self.current_pos.x, self.current_pos.y)

    # If a friendly bridge already exists at source, treat pending bridge as complete.
    if (
        build_id is not None
        and entity_type == EntityType.BRIDGE
        and c.get_team(build_id) == c.get_team()
    ):
        self.bridge_from = None
        self.post_bridge_conveyor = True
        self.return_bridge_fail_counts.pop(key, None)
        return True

    if (
        build_id is not None
        and entity_type in (EntityType.ROAD, EntityType.CONVEYOR)
        and c.get_team(build_id) == c.get_team()
        and c.can_destroy(bridge_pos)
    ):
        c.destroy(bridge_pos)
        _mark_network_reach_dirty(self)

    can_build_bridge = c.can_build_bridge(bridge_pos, self.current_pos)
    if can_build_bridge:
        c.build_bridge(bridge_pos, self.current_pos)
        _mark_network_reach_dirty(self)
        self.bridge_from = None
        self.post_bridge_conveyor = True
        self.return_bridge_fail_counts.pop(key, None)
        return True

    # If we simply can't afford the bridge yet, wait without counting a failure.
    ti, _ = c.get_global_resources()
    bridge_cost_ti, _ = c.get_bridge_cost()
    if ti < bridge_cost_ti:
        return False

    fails = self.return_bridge_fail_counts.get(key, 0) + 1
    self.return_bridge_fail_counts[key] = fails
    if fails >= _MAX_BRIDGE_FAILS:
        self.bridge_from = None
        self.post_bridge_conveyor = True
        self.return_bridge_fail_counts.pop(key, None)
        return True

    return False


def _ensure_post_bridge_conveyor(self: Harvester, c: Controller) -> bool:
    if not self.post_bridge_conveyor:
        return False

    if reached_core(self.current_pos, self.core_pos):
        self.post_bridge_conveyor = False
        return True

    conveyor_dir = _planner_step_at(self, c, self.current_pos)
    if conveyor_dir is None or conveyor_dir == Direction.CENTRE:
        conveyor_dir = get_direction_4(self.current_pos, self.core_pos)
    elif conveyor_dir not in DIRECTIONS_4:
        _, split, _ = _resolve_diagonal_plan(self, c, self.current_pos, conveyor_dir)
        conveyor_dir = split[0] if split else get_direction_4(self.current_pos, self.core_pos)
    if conveyor_dir is None:
        self.post_bridge_conveyor = False
        return False

    cleared = _clear_return_tile(self, c, self.current_pos)
    if not cleared:
        return False

    tile_empty = c.get_tile_env(self.current_pos) == Environment.EMPTY
    if tile_empty:
        ti, _ = c.get_global_resources()
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if ti < conveyor_cost_ti:
            return False

    if tile_empty and c.can_build_conveyor(self.current_pos, conveyor_dir):
        c.build_conveyor(self.current_pos, conveyor_dir)
        _mark_network_reach_dirty(self)

    self.post_bridge_conveyor = False
    return True

def _try_shortcut_step(self: Harvester, c: Controller, move_dir: Direction) -> bool:
    """Move one tile in `move_dir`, paving an empty tile with a road if needed."""
    if c.can_move(move_dir):
        c.move(move_dir)
        return True
    step_pos = self.current_pos.add(move_dir)
    if c.get_tile_env(step_pos) == Environment.EMPTY and c.can_build_road(step_pos):
        c.build_road(step_pos)
        if c.can_move(move_dir):
            c.move(move_dir)
            return True
    return False


def _step_to_shortcut_target(self: Harvester, c: Controller) -> bool:
    """Walk one step toward `shortcut_target` without building conveyors.

    Follows the return planner's next step rather than `direction_to(target)`
    — the shortcut is selected precisely because the direct path to `end`
    winds around walls, so direction_to would happily point through the wall
    the bridge spans. The planner's _RETURN_BLOCK_MASK excludes walls/ores,
    so each planner step is onto a tile that's already walkable or paveable.

    Stays put on a blocked tick rather than clearing `shortcut_target` — the
    bridge is already paid for, so retrying next tick avoids re-entering
    `_shortcut_path` with a fresh bridge build.
    """
    if self.shortcut_target is None:
        return False

    move_dir = _planner_step_at(self, c, self.current_pos)
    if move_dir is None or move_dir == Direction.CENTRE:
        move_dir = self.current_pos.direction_to(self.shortcut_target)
    if move_dir == Direction.CENTRE:
        return False

    if _try_shortcut_step(self, c, move_dir):
        return True

    if move_dir not in DIRECTIONS_4:
        ns, ew = split_diagonal(self.current_pos, self.current_pos.add(move_dir))
        for candidate in (ns, ew):
            if candidate is not None and _try_shortcut_step(self, c, candidate):
                return True

    return False


def _handle_shortcut_walk(self: Harvester, c: Controller) -> bool:
    """Dispatched from `_return` while `shortcut_target` is set.

    On arrival, drop the receiving conveyor at the bridge target so the bridge
    output has something to feed into, then let the normal flow resume next
    tick. Otherwise, take one step toward the target (paving a road on an
    empty blocked tile if needed). Never builds a bridge.
    """
    if self.shortcut_target is None:
        return False

    if self.current_pos == self.shortcut_target:
        self.shortcut_target = None
        self.post_bridge_conveyor = True
        return _ensure_post_bridge_conveyor(self, c)

    return _step_to_shortcut_target(self, c)


def _shortcut_path(path: list[tuple[int, int]], threshold: int = 5) -> tuple[Position, list[tuple[int, int]]] | None:
    if len(path) < 5:
        return None

    x1, y1 = path[0]
    best = -1
    for i in range(len(path) - 1, 0, -1):
        x2, y2 = path[i]
        if (x1 - x2) ** 2 + (y1 - y2) ** 2 <= 9:
            best = i
            break

    if best == -1 or best < threshold:
        return None

    return Position(x1, y1), path[:1] + path[best:]
