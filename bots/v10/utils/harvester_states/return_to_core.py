
from enum import Enum, auto

from cambc import Direction, EntityType, Environment, Position

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


class _DiagonalKind(Enum):
    NONE = auto()
    SPLIT = auto()
    BRIDGE_NOW = auto()


_MAX_BRIDGE_FAILS = 3


def _mark_network_reach_dirty(self) -> None:
    self.network_reach_dirty = True


def _reachable_to_core(self, c) -> set[tuple[int, int]]:
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


def _receiver_accepts_from(self, c, source_pos: Position, receiver_pos: Position, receiver_id: int) -> bool:
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


def _harvester_attached_to_core(self, c) -> bool:
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



def _reset_return_state(self):
    self.bridge_from = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}


def _return_dynamic_blockers(c) -> list[tuple[int, int]]:
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

def _ensure_return_planner(self, c):
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


def _refresh_return_planner(self, c) -> tuple[Direction | None, list[tuple[int, int]]]:
    planner = _ensure_return_planner(self, c)
    if planner is None:
        return None, []
    planner.set_position(self.current_pos.x, self.current_pos.y)
    step = planner.step()
    path = planner.extract_path()
    return step, path


def _planner_step_at(self, c, pos: Position) -> Direction | None:
    planner = _ensure_return_planner(self, c)
    if planner is None:
        return None
    planner.set_position(pos.x, pos.y)
    step = planner.step()
    if step == Direction.CENTRE:
        return None
    return step


def _ordered_split(self, origin, move_dir: Direction) -> list[Direction] | None:
    ns, ew = split_diagonal(origin, origin.add(move_dir))
    if ns is None or ew is None:
        return None
    preferred = get_direction_4(origin, self.core_pos)
    if preferred == ew:
        return [ew, ns]
    return [ns, ew]


def _resolve_diagonal_plan(
    self,
    c,
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

    if origin == self.current_pos and c.can_move(move_dir):
        return _DiagonalKind.BRIDGE_NOW, None, move_dir

    return _DiagonalKind.NONE, None, None


def _next_dir_after_move(
    self,
    c,
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




def _is_return_tile_usable(self, c, pos) -> bool:
    if reached_core(pos, self.core_pos):
        return True

    if not c.is_in_vision(pos):
        if not on_map(c, pos):
            return False
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


def _clear_return_tile(self, c, pos) -> bool:
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


def _can_execute_return_step(self, c, move_dir: Direction, next_move_dir: Direction | None) -> bool:
    if c.can_move(move_dir):
        return True

    move_pos = self.current_pos.add(move_dir)
    if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
        return True

    if next_move_dir is None:
        return False

    return c.can_build_conveyor(move_pos, next_move_dir)


def _build_first_connector(self, c) -> bool:
    move_pos = self.current_pos

    # If the harvester was diagonal, pick one of the two cardinal join tiles.
    if self.harvester_pos and is_diagonal(self.current_pos, self.harvester_pos):
        ns, ew = split_diagonal(self.current_pos, self.harvester_pos)
        m1 = self.current_pos.add(ns)
        m2 = self.current_pos.add(ew)
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
        _, split, _ = _resolve_diagonal_plan(self, c, move_pos, step)
        if not split:
            return False
        step = split[0]
    conveyor_dir = step

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


def _build_return_step(self, c) -> bool:
    planner_step, planner_path = _refresh_return_planner(self, c)
    carry_next: Direction | None = None

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
    if next_dir is not None and c.can_build_conveyor(move_pos, next_dir):
        c.build_conveyor(move_pos, next_dir)
        _mark_network_reach_dirty(self)
    elif dest_empty and c.can_build_road(move_pos):
        c.build_road(move_pos)
    if not c.can_move(move_dir):
        return False
    self.return_next_dir = carry_next
    c.move(move_dir)
    return True


def _handle_return_diagonal_step(self, c, move_dir: Direction) -> bool:
    move_pos = self.current_pos.add(move_dir)
    self.return_next_dir = None

    if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if c.can_move(move_dir):
        self.bridge_from = self.current_pos
        c.move(move_dir)
        return True

    return False


def _handle_pending_return_bridge(self, c) -> bool:
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

    fails = self.return_bridge_fail_counts.get(key, 0) + 1
    self.return_bridge_fail_counts[key] = fails
    if fails >= _MAX_BRIDGE_FAILS:
        self.bridge_from = None
        self.post_bridge_conveyor = True
        self.return_bridge_fail_counts.pop(key, None)
        return True

    return False


def _ensure_post_bridge_conveyor(self, c) -> bool:
    if not self.post_bridge_conveyor:
        return False

    if reached_core(self.current_pos, self.core_pos):
        self.post_bridge_conveyor = False
        return True

    conveyor_dir = _planner_step_at(self, c, self.current_pos)
    if conveyor_dir is None or conveyor_dir not in DIRECTIONS_4:
        conveyor_dir = get_direction_4(self.current_pos, self.core_pos)
    if conveyor_dir is None:
        self.post_bridge_conveyor = False
        return False

    cleared = _clear_return_tile(self, c, self.current_pos)
    if not cleared:
        return False

    can_build_conveyor = (
        c.get_tile_env(self.current_pos) == Environment.EMPTY
        and c.can_build_conveyor(self.current_pos, conveyor_dir)
    )
    if can_build_conveyor:
        c.build_conveyor(self.current_pos, conveyor_dir)
        _mark_network_reach_dirty(self)

    self.post_bridge_conveyor = False
    return True
