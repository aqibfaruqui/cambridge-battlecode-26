
from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, Controller

from utils.pathfinding.d_star import DStarLite, _RETURN_BLOCK_MASK
from utils.map.raw_map_representation import CORE_OWN, ORE_AXIONITE, TRAVERSABLE, UNKNOWN
from utils.pathfinding.movement import (
    DIRECTIONS_4,
    get_direction_4,
    is_diagonal,
    on_map,
    reached_core,
    split_diagonal,
)

if TYPE_CHECKING:
    from builders.harvester import Harvester


_MAX_BRIDGE_FAILS = 3

_ENEMY_WALKABLE_TYPES = (
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.ROAD,
)


def _harvester_attached_to_core(self: Harvester, c: Controller) -> bool:
    """Check if the conveyor chain from current position is connected to core."""
    # TODO: Implement this
    return False


def _reset_return_state(self: Harvester):
    self.bridge_from = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}
    self.return_jump_walker = None
    self.return_jump_landing = None


def _enemy_walkable_at(c: Controller, pos: Position) -> bool:
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return False
    if c.get_team(bid) == c.get_team():
        return False
    return c.get_entity_type(bid) in _ENEMY_WALKABLE_TYPES


def _attack_enemy_under_bot(self: Harvester, c: Controller) -> bool:
    if not _enemy_walkable_at(c, self.current_pos):
        return False
    if c.can_fire(self.current_pos):
        c.fire(self.current_pos)
        if c.get_tile_building_id(self.current_pos) is None:
            self.post_bridge_conveyor = True
    return True


def _return_dynamic_blockers(c: Controller) -> list[tuple[int, int]]:
    team = c.get_team()
    blockers: list[tuple[int, int]] = []
    for pos in c.get_nearby_tiles():
        build_id = c.get_tile_building_id(pos)
        if build_id is None:
            continue
        entity_type = c.get_entity_type(build_id)
        if entity_type == EntityType.MARKER:
            continue
        if entity_type == EntityType.HARVESTER or c.get_team(build_id) != team:
            blockers.append((pos.x, pos.y))
    return blockers


def _blacklist_landing(self: Harvester, landing_xy: tuple[int, int]) -> None:
    """Permanently mark a jump landing as unreachable for this harvester.
    Clears any in-flight traversal state. The next _ensure_return_jump_planner
    call propagates the blacklist into the jump planner's dynamic blockers."""
    self.return_jump_blacklist.add(landing_xy)
    self.return_jump_walker = None
    self.return_jump_landing = None


def _ensure_return_planner(self: Harvester, c: Controller):
    if self.return_planner is None and self.environment_map is not None:
        self.return_planner = DStarLite(
            self.environment_map,
            self.core_pos.x,
            self.core_pos.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
        )
    p = self.return_planner
    if p is not None:
        p.set_dynamic_blockers(_return_dynamic_blockers(c))
        p.notify_map_changes()
    return p


def _planner_step_at(self: Harvester, c: Controller, pos: Position) -> Direction | None:
    p = _ensure_return_planner(self, c)
    if p is None:
        return None
    p.set_position(pos.x, pos.y)
    step = p.step()
    return None if step == Direction.CENTRE else step


def _is_return_tile_usable(self: Harvester, c: Controller, pos: Position, check_occupancy: bool = True) -> bool:
    """Check if a tile is usable for return pathfinding. With bool for checking if tile has been occupied by another builder bot"""
    if reached_core(pos, self.core_pos):
        return True
    if not c.is_in_vision(pos):
        if not on_map(c, pos):
            return False
        env = self.environment_map
        if env is None:
            return False
        return env.tile(pos.x, pos.y) in (TRAVERSABLE, ORE_AXIONITE, CORE_OWN, UNKNOWN)
    if c.get_tile_env(pos) == Environment.WALL:
        return False
    if check_occupancy:
        occupier = c.get_tile_builder_bot_id(pos)
        if occupier is not None and occupier != c.get_id():
            return False
    build_id = c.get_tile_building_id(pos)
    if build_id is None:
        return True
    entity_type = c.get_entity_type(build_id)
    if entity_type in (EntityType.ROAD, EntityType.CORE, EntityType.MARKER):
        return True
    if c.get_team(build_id) != c.get_team():
        return False
    return entity_type in (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER)


def _clear_return_tile(_: Harvester, c: Controller, pos: Position) -> bool:
    build_id = c.get_tile_building_id(pos)
    if build_id is None:
        return True
    entity_type = c.get_entity_type(build_id)
    if entity_type in (EntityType.MARKER, EntityType.CORE):
        return True
    if entity_type == EntityType.ROAD:
        if c.can_destroy(pos):
            c.destroy(pos)
            return True
        return False
    if c.get_team(build_id) != c.get_team():
        return False
    return entity_type in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE)


def _resolve_diagonal(self: Harvester, c: Controller, origin: Position, move_dir: Direction) -> tuple[list[Direction] | None, Direction | None]:
    """Returns (split_dirs, bridge_dir). split_dirs is a two-step cardinal path;
    bridge_dir means go diagonally and build a bridge behind. Both None = unresolvable."""
    ns, ew = split_diagonal(origin, origin.add(move_dir))
    if ns is None or ew is None:
        return None, None

    preferred = get_direction_4(origin, self.core_pos)
    ordered = [ew, ns] if preferred == ew else [ns, ew]

    for first, second in [(ordered[0], ordered[1]), (ordered[1], ordered[0])]:
        first_pos = origin.add(first)
        second_pos = first_pos.add(second)
        if not _is_return_tile_usable(self, c, first_pos, check_occupancy=False):
            continue
        if reached_core(first_pos, self.core_pos):
            return [first], None
        if _is_return_tile_usable(self, c, second_pos, check_occupancy=False):
            return [first, second], None

    if origin == self.current_pos:
        diag_pos = origin.add(move_dir)
        if c.can_move(move_dir) or (
            c.get_tile_env(diag_pos) == Environment.EMPTY and c.can_build_road(diag_pos)
        ):
            return None, move_dir

    return None, None


def _next_dir_after_move(self: Harvester, c: Controller, move_dir: Direction, planner_path: list[tuple[int, int]]) -> Direction | None:
    """Conveyor direction to place on the tile we're about to step onto."""
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

    split, _ = _resolve_diagonal(self, c, move_pos, follow_dir)
    if split:
        return split[0]
    ns, ew = split_diagonal(move_pos, move_pos.add(follow_dir))
    return ns or ew


def _to_cardinal(self: Harvester, c: Controller, origin: Position, raw_dir: Direction) -> tuple[Direction | None, Direction | None, Direction | None]:
    """Resolve a diagonal raw_dir to a cardinal step.
    Returns (move_dir, carry_next, bridge_dir): bridge_dir set means caller should take a
    diagonal bridge step; all None means unresolvable."""
    if raw_dir in DIRECTIONS_4:
        return raw_dir, None, None
    split, bridge_dir = _resolve_diagonal(self, c, origin, raw_dir)
    if bridge_dir is not None:
        return None, None, bridge_dir
    if split:
        return split[0], split[1] if len(split) > 1 else None, None
    return None, None, None


def _handle_diagonal_step(self: Harvester, c: Controller, move_dir: Direction) -> bool:
    move_pos = self.current_pos.add(move_dir)
    self.return_next_dir = None
    if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
        c.build_road(move_pos)
    if c.can_move(move_dir):
        self.bridge_from = self.current_pos
        c.move(move_dir)
        return True
    return False


def _handle_bridge_state(self: Harvester, c: Controller) -> bool:
    """Handle a pending bridge build or the post-bridge conveyor. Returns True if the turn is consumed."""
    if self.bridge_from is not None:
        bridge_pos = self.bridge_from
        build_id = c.get_tile_building_id(bridge_pos)
        entity_type = c.get_entity_type(build_id) if build_id is not None else None
        key = (bridge_pos.x, bridge_pos.y, self.current_pos.x, self.current_pos.y)

        if build_id is not None and entity_type == EntityType.BRIDGE and c.get_team(build_id) == c.get_team():
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

        if c.can_build_bridge(bridge_pos, self.current_pos):
            c.build_bridge(bridge_pos, self.current_pos)
            self.bridge_from = None
            self.post_bridge_conveyor = True
            self.return_bridge_fail_counts.pop(key, None)
            return True

        ti, _ = c.get_global_resources()
        bridge_cost_ti, _ = c.get_bridge_cost()
        if ti >= bridge_cost_ti:
            fails = self.return_bridge_fail_counts.get(key, 0) + 1
            self.return_bridge_fail_counts[key] = fails
            if fails >= _MAX_BRIDGE_FAILS:
                self.bridge_from = None
                self.post_bridge_conveyor = True
                self.return_bridge_fail_counts.pop(key, None)
        return True  # always wait while bridge is pending

    if self.post_bridge_conveyor:
        if reached_core(self.current_pos, self.core_pos):
            self.post_bridge_conveyor = False
            return True

        conveyor_dir = _planner_step_at(self, c, self.current_pos)
        if conveyor_dir is None or conveyor_dir == Direction.CENTRE:
            conveyor_dir = get_direction_4(self.current_pos, self.core_pos)
        elif conveyor_dir not in DIRECTIONS_4:
            split, _ = _resolve_diagonal(self, c, self.current_pos, conveyor_dir)
            conveyor_dir = split[0] if split else get_direction_4(self.current_pos, self.core_pos)
        if conveyor_dir is None:
            self.post_bridge_conveyor = False
            return False

        bid = c.get_tile_building_id(self.current_pos)
        if (
            bid is not None
            and c.get_entity_type(bid) == EntityType.CONVEYOR
            and c.get_team(bid) == c.get_team()
            and c.get_direction(bid) != conveyor_dir
            and c.can_destroy(self.current_pos)
        ):
            c.destroy(self.current_pos)
            return True  # wait for tile to clear before rebuilding

        if _clear_return_tile(self, c, self.current_pos):
            tile_empty = c.get_tile_env(self.current_pos) == Environment.EMPTY
            ti, _ = c.get_global_resources()
            conveyor_cost_ti, _ = c.get_conveyor_cost()
            if not tile_empty or ti >= conveyor_cost_ti:
                if tile_empty and c.can_build_conveyor(self.current_pos, conveyor_dir):
                    c.build_conveyor(self.current_pos, conveyor_dir)
                    self.return_next_dir = conveyor_dir
                self.post_bridge_conveyor = False

        return True  # always wait while post-bridge conveyor is pending

    return False


def _build_return_step(self: Harvester, c: Controller) -> bool:
    # On the first turn after placing a harvester, place a connector conveyor on
    # the starting tile (choosing the closer cardinal join tile when the placement
    # was diagonal) so the chain begins before the normal walk-back loop takes over.
    if self.just_placed:
        move_pos = self.current_pos
        if self.harvester_pos and is_diagonal(self.current_pos, self.harvester_pos):
            ns, ew = split_diagonal(self.current_pos, self.harvester_pos)
            m1 = self.current_pos.add(ns)  # type: ignore
            m2 = self.current_pos.add(ew)  # type: ignore
            move_pos = m1 if m1.distance_squared(self.core_pos) < m2.distance_squared(self.core_pos) else m2

        build_id = c.get_tile_building_id(move_pos)
        if build_id is not None and c.get_entity_type(build_id) in {EntityType.ROAD, EntityType.CONVEYOR} and c.can_destroy(move_pos):
            c.destroy(move_pos)

        step = _planner_step_at(self, c, move_pos) or move_pos.direction_to(self.core_pos)
        if step is None or step == Direction.CENTRE:
            return False
        if step not in DIRECTIONS_4:
            step, _, bridge_dir = _to_cardinal(self, c, move_pos, step)
            if bridge_dir is not None:
                self.just_placed = False
                return _handle_diagonal_step(self, c, bridge_dir)
            if step is None:
                return False

        if c.get_tile_building_id(move_pos) is None:
            conveyor_cost_ti, _ = c.get_conveyor_cost()
            if self.ti < conveyor_cost_ti:
                return False
        if c.can_build_conveyor(move_pos, step):
            c.build_conveyor(move_pos, step)

        step_dir = get_direction_4(self.current_pos, move_pos) if self.current_pos != move_pos else None
        if step_dir and not c.can_move(step_dir):
            return False
        self.just_placed = False
        self.return_next_dir = step
        if step_dir:
            c.move(step_dir)
        return True

    planner = _ensure_return_planner(self, c)
    planner_step: Direction | None = None
    planner_path: list[tuple[int, int]] = []
    if planner is not None:
        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner_step = planner.step()
        planner_path = planner.extract_path()
    carry_next: Direction | None = None

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
            move_dir, carry_next, bridge_dir = _to_cardinal(self, c, self.current_pos, move_dir)
            if bridge_dir is not None:
                return _handle_diagonal_step(self, c, bridge_dir)
            if move_dir is None:
                return False

    next_dir = _next_dir_after_move(self, c, move_dir, planner_path)
    if carry_next is not None:
        next_dir = carry_next

    move_pos = self.current_pos.add(move_dir)

    if next_dir is not None:
        bid = c.get_tile_building_id(move_pos)
        if (
            bid is not None
            and c.get_entity_type(bid) == EntityType.CONVEYOR
            and c.get_team(bid) == c.get_team()
            and c.get_direction(bid) != next_dir
            and c.can_destroy(move_pos)
        ):
            c.destroy(move_pos)
            return False

    build_id = c.get_tile_building_id(move_pos)
    if reached_core(move_pos, self.core_pos) or (
        build_id is not None and c.get_entity_type(build_id) == EntityType.CORE
    ):
        if not c.can_move(move_dir):
            return False
        c.move(move_dir)
        return True

    if _enemy_walkable_at(c, move_pos):
        if not c.can_move(move_dir):
            return False
        self.return_next_dir = next_dir
        c.move(move_dir)
        return True

    if not c.can_move(move_dir):
        can_execute = False
        if c.get_tile_env(move_pos) == Environment.EMPTY:
            bid = c.get_tile_building_id(move_pos)
            if bid is not None and c.get_entity_type(bid) == EntityType.MARKER:
                can_execute = True
            elif c.can_build_road(move_pos):
                can_execute = True
        if not can_execute and next_dir is not None:
            can_execute = c.can_build_conveyor(move_pos, next_dir)
        if not can_execute:
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
    elif dest_empty and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if not c.can_move(move_dir):
        return False
    self.return_next_dir = next_dir
    c.move(move_dir)
    return True
