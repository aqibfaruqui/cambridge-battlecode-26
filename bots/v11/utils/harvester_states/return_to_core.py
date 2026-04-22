
from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, Controller

from utils.pathfinding.d_star import DStarLite, _RETURN_BLOCK_MASK, _SEEK_BLOCK_MASK
from utils.pathfinding.movement import (
    DIRECTIONS_4,
    get_direction_4,
    is_diagonal,
    split_diagonal,
    reached_core,
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


def _reset_return_state(self: Harvester):
    self.bridge_jump_target = None
    self.bridge_target_planner = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}


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


def _ensure_return_planner(self: Harvester, c: Controller):
    if self.return_planner is None and self.environment_map is not None:
        self.return_planner = DStarLite(
            self.environment_map,
            self.core_pos.x,
            self.core_pos.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
            use_bridges=True,
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


def _next_dir_after_move(self: Harvester, c: Controller, move_dir: Direction) -> Direction | None:
    """Conveyor direction to place on the tile we're about to step onto."""
    move_pos = self.current_pos.add(move_dir)
    follow_dir = _planner_step_at(self, c, move_pos) or move_pos.direction_to(self.core_pos)
    if follow_dir is None or follow_dir == Direction.CENTRE:
        return None
    if follow_dir in DIRECTIONS_4:
        return follow_dir
    return get_direction_4(move_pos, move_pos.add(follow_dir))


def _handle_post_bridge_conveyor(self: Harvester, c: Controller) -> bool:
    """Place conveyor on current tile after crossing a bridge. Returns True while consuming the turn."""
    if not self.post_bridge_conveyor:
        return False

    if reached_core(self.current_pos, self.core_pos):
        self.post_bridge_conveyor = False
        return True

    conveyor_dir = _planner_step_at(self, c, self.current_pos)
    if conveyor_dir is None or conveyor_dir == Direction.CENTRE or conveyor_dir not in DIRECTIONS_4:
        conveyor_dir = get_direction_4(self.current_pos, self.core_pos)
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
        return True

    if _clear_return_tile(self, c, self.current_pos):
        tile_empty = c.get_tile_env(self.current_pos) == Environment.EMPTY
        ti, _ = c.get_global_resources()
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if not tile_empty or ti >= conveyor_cost_ti:
            if tile_empty and c.can_build_conveyor(self.current_pos, conveyor_dir):
                c.build_conveyor(self.current_pos, conveyor_dir)
                self.return_next_dir = conveyor_dir
            self.post_bridge_conveyor = False

    return True


def _handle_bridge_jump(self: Harvester, c: Controller, target_pos: Position) -> bool:
    """Build a bridge to target_pos if not built yet, then walk across it."""
    bridge_pos = self.current_pos

    if self.bridge_jump_target is not None:
        return _walk_toward_bridge_target(self, c)

    bid = c.get_tile_building_id(bridge_pos)
    if bid is not None and c.get_entity_type(bid) == EntityType.BRIDGE and c.get_team(bid) == c.get_team():
        self.bridge_jump_target = target_pos
        return _walk_toward_bridge_target(self, c)

    entity_type = c.get_entity_type(bid) if bid is not None else None
    if (
        bid is not None
        and entity_type in (EntityType.ROAD, EntityType.CONVEYOR)
        and c.get_team(bid) == c.get_team()
        and c.can_destroy(bridge_pos)
    ):
        c.destroy(bridge_pos)
        return True

    if c.can_build_bridge(bridge_pos, target_pos):
        c.build_bridge(bridge_pos, target_pos)
        self.bridge_jump_target = target_pos
        return True

    ti, _ = c.get_global_resources()
    bridge_cost_ti, _ = c.get_bridge_cost()
    if ti >= bridge_cost_ti:
        key = (bridge_pos.x, bridge_pos.y, target_pos.x, target_pos.y)
        fails = self.return_bridge_fail_counts.get(key, 0) + 1
        self.return_bridge_fail_counts[key] = fails
        if fails >= _MAX_BRIDGE_FAILS:
            self.return_planner = None
            self.return_bridge_fail_counts.pop(key, None)
    return True


def _ensure_bridge_target_planner(self: Harvester, c: Controller, target: Position) -> DStarLite | None:
    if self.bridge_target_planner is None and self.environment_map is not None:
        self.bridge_target_planner = DStarLite(
            self.environment_map,
            target.x,
            target.y,
            block_mask=_SEEK_BLOCK_MASK,
        )
    p = self.bridge_target_planner
    if p is not None:
        p.set_position(self.current_pos.x, self.current_pos.y)
        p.set_dynamic_blockers(_return_dynamic_blockers(c))
        p.notify_map_changes()
    return p


def _walk_toward_bridge_target(self: Harvester, c: Controller) -> bool:
    target = self.bridge_jump_target
    if target is None:
        return False

    if self.current_pos == target:
        self.bridge_jump_target = None
        self.bridge_target_planner = None
        self.post_bridge_conveyor = True
        return True

    p = _ensure_bridge_target_planner(self, c, target)
    move_dir = None
    if p is not None:
        d = p.step()
        if d is not None and d != Direction.CENTRE:
            move_dir = d

    if move_dir is None:
        move_dir = self.current_pos.direction_to(target)
    if move_dir is None or move_dir == Direction.CENTRE:
        self.bridge_jump_target = None
        self.bridge_target_planner = None
        self.post_bridge_conveyor = True
        return True

    move_pos = self.current_pos.add(move_dir)
    if c.can_build_road(move_pos):
        c.build_road(move_pos)
    if c.can_move(move_dir):
        c.move(move_dir)
    return True


def _build_return_step(self: Harvester, c: Controller) -> bool:
    if self.bridge_jump_target is not None:
        return _walk_toward_bridge_target(self, c)

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
            step = get_direction_4(move_pos, self.core_pos)
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
    if planner is not None:
        planner.set_position(self.current_pos.x, self.current_pos.y)

        step_xy = planner.step_xy()
        if step_xy is not None:
            cx, cy = self.current_pos.x, self.current_pos.y
            tx, ty = step_xy
            dsq = (tx - cx) * (tx - cx) + (ty - cy) * (ty - cy)
            if dsq > 1:
                return _handle_bridge_jump(self, c, Position(tx, ty))
            planner_step = self.current_pos.direction_to(Position(tx, ty))

    if self.return_next_dir is not None:
        move_dir = self.return_next_dir
        self.return_next_dir = None
    else:
        move_dir = planner_step
        if move_dir is None or move_dir == Direction.CENTRE:
            move_dir = self.current_pos.direction_to(self.core_pos)
        if move_dir is None or move_dir == Direction.CENTRE:
            return False

    next_dir = _next_dir_after_move(self, c, move_dir)

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
