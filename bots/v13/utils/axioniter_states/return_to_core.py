from __future__ import annotations
from typing import TYPE_CHECKING, Any, cast

from cambc import Direction, EntityType, Environment, Position, Controller, ResourceType

from utils.pathfinding.d_star import (
    DSTAR_CPU_DEADLINE_US,
    DStarLite,
    _RETURN_BLOCK_MASK,
)
from utils.pathfinding.movement import (
    DIRECTIONS_4,
    get_direction_4,
    is_diagonal,
    reached_core,
    split_diagonal,
)
from utils.harvester_states.return_to_core import (
    _build_return_step as _harvester_build_return_step,
    _handle_post_bridge_conveyor as _harvester_handle_post_bridge_conveyor,
)

if TYPE_CHECKING:
    from builders.axioniter import Axioniter


_MAX_BRIDGE_FAILS = 3

_ENEMY_WALKABLE_TYPES = (
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.ROAD,
)
_CHAIN_MEMORY_TTL = 80
_TRANSPORT_TYPES = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
}
_ACTION_RADIUS_OFFSETS = (
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (0, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
)

_FOUNDRY_REPLACEABLE_TYPES = {
    EntityType.ROAD,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
}
_FEED_REPLACEABLE_TYPES = {
    EntityType.MARKER,
    EntityType.ROAD,
    EntityType.CONVEYOR,
}


def _reset_return_state(self: Axioniter):
    self.bridge_jump_target = None
    self.bridge_target_planner = None
    self.return_next_dir = None
    self.return_chain_cursor = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}
    self.failed_bridge_targets.clear()


def _same_pos(a: Position | None, b: Position | None) -> bool:
    return a is not None and b is not None and a.x == b.x and a.y == b.y


def _clear_bridge_walk_state(
    self: Axioniter, *, reset_return_planner: bool = False
) -> None:
    self.bridge_jump_target = None
    self.bridge_target_planner = None
    if reset_return_planner:
        self.return_planner = None


def _start_bridge_walk(self: Axioniter, target: Position) -> None:
    self.bridge_jump_target = target
    self.bridge_target_planner = None


def _bridge_target_matches(c: Controller, bridge_id: int, target: Position) -> bool:
    try:
        return _same_pos(c.get_bridge_target(bridge_id), target)
    except Exception:
        return True


def _bridge_fail(self: Axioniter, key) -> None:
    fails = self.return_bridge_fail_counts.get(key, 0) + 1
    self.return_bridge_fail_counts[key] = fails
    if fails >= _MAX_BRIDGE_FAILS:
        if self.bridge_jump_target is not None:
            self.failed_bridge_targets.add(
                (self.bridge_jump_target.x, self.bridge_jump_target.y)
            )
        _clear_bridge_walk_state(self, reset_return_planner=True)
        self.return_bridge_fail_counts.pop(key, None)


def _post_bridge_fail(self: Axioniter, key) -> None:
    fails = self.return_bridge_fail_counts.get(key, 0) + 1
    self.return_bridge_fail_counts[key] = fails
    if fails >= _MAX_BRIDGE_FAILS:
        self.post_bridge_conveyor = False
        self.return_planner = None
        self.return_bridge_fail_counts.pop(key, None)


def _enemy_walkable_at(c: Controller, pos: Position) -> bool:
    if not _on_map(c, pos) or not c.is_in_vision(pos):
        return False
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return False
    if c.get_team(bid) == c.get_team():
        return False
    return c.get_entity_type(bid) in _ENEMY_WALKABLE_TYPES


def _attack_enemy_under_bot(self: Axioniter, c: Controller) -> bool:
    if not _enemy_walkable_at(c, self.current_pos):
        return False
    if not c.can_fire(self.current_pos):
        return False
    c.fire(self.current_pos)
    if c.get_tile_building_id(self.current_pos) is None:
        self.post_bridge_conveyor = True
    return True


def _blocks_foundry_outbound(
    self: Axioniter,
    c: Controller,
    pos: Position,
    build_id: int,
    entity_type: EntityType,
) -> bool:
    foundry_pos = self.outbound_foundry_pos
    if foundry_pos is None or entity_type not in _TRANSPORT_TYPES:
        return False
    if c.get_team(build_id) != c.get_team():
        return False
    out = _transport_output(c, pos, build_id)
    if _same_pos(out, foundry_pos):
        return True
    return c.get_stored_resource(build_id) == ResourceType.RAW_AXIONITE


def _chain_reaches_allied_foundry(c: Controller, pos: Position) -> bool:
    current = pos
    seen: set[tuple[int, int]] = set()
    max_hops = min(16, c.get_map_width() + c.get_map_height())
    for _ in range(max_hops):
        key = (current.x, current.y)
        if key in seen or not _on_map(c, current) or not c.is_in_vision(current):
            return False
        seen.add(key)
        bid = c.get_tile_building_id(current)
        if bid is None or c.get_team(bid) != c.get_team():
            return False
        etype = c.get_entity_type(bid)
        if etype == EntityType.FOUNDRY:
            return True
        if etype == EntityType.CORE:
            return False
        if etype not in _TRANSPORT_TYPES:
            return False
        out = _transport_output(c, current, bid)
        if out is None:
            return False
        current = out
    return False


def _is_foundry_chain_blocker(
    c: Controller, pos: Position, build_id: int, entity_type: EntityType
) -> bool:
    if entity_type not in _TRANSPORT_TYPES or c.get_team(build_id) != c.get_team():
        return False
    return _chain_reaches_allied_foundry(c, pos)


def _return_dynamic_blockers(self: Axioniter, c: Controller) -> list[tuple[int, int]]:
    team = c.get_team()
    blockers: list[tuple[int, int]] = []
    for pos in c.get_nearby_tiles():
        build_id = c.get_tile_building_id(pos)
        if build_id is None:
            continue
        entity_type = c.get_entity_type(build_id)
        if entity_type == EntityType.MARKER:
            continue
        if (
            entity_type in (EntityType.HARVESTER, EntityType.FOUNDRY)
            or c.get_team(build_id) != team
            or _blocks_foundry_outbound(self, c, pos, build_id, entity_type)
        ):
            blockers.append((pos.x, pos.y))
    return blockers


def _body_dynamic_blockers(self: Axioniter, c: Controller) -> list[tuple[int, int]]:
    blockers = _return_dynamic_blockers(self, c)
    my_id = c.get_id()
    for pos in c.get_nearby_tiles():
        bot_id = c.get_tile_builder_bot_id(pos)
        if bot_id is not None and bot_id != my_id:
            blockers.append((pos.x, pos.y))
    return blockers


def _escape_foundry_input_chain(self: Axioniter, c: Controller) -> bool:
    build_id = c.get_tile_building_id(self.current_pos)
    if build_id is None:
        return False
    entity_type = c.get_entity_type(build_id)
    if not _is_foundry_chain_blocker(c, self.current_pos, build_id, entity_type):
        return False

    goal = self.return_target_pos or self.core_pos
    candidates: list[Direction] = []
    for direction in DIRECTIONS_4:
        pos = self.current_pos.add(direction)
        if not _on_map(c, pos) or not c.is_in_vision(pos):
            continue
        bid = c.get_tile_building_id(pos)
        if bid is not None:
            etype = c.get_entity_type(bid)
            if c.get_team(bid) != c.get_team() or etype in (
                EntityType.HARVESTER,
                EntityType.FOUNDRY,
            ):
                continue
            if _is_foundry_chain_blocker(c, pos, bid, etype):
                continue
        if c.can_move(direction):
            candidates.append(direction)
    candidates.sort(key=lambda d: self.current_pos.add(d).distance_squared(goal))
    if candidates:
        c.move(candidates[0])
        self.return_planner = None
        self.return_next_dir = None
        return True
    self.harvester_pos = None
    self.returning_from_axionite = False
    self.state = type(self.state).SEEK
    _reset_return_state(self)
    return True


def _chain_reaches_return_goal(self: Axioniter, c: Controller, pos: Position) -> bool:
    goal = self.return_target_pos
    if goal is None:
        return False
    current = pos
    seen: set[tuple[int, int]] = set()
    max_hops = min(16, c.get_map_width() + c.get_map_height())
    for _ in range(max_hops):
        if _same_pos(current, goal) or _at_return_goal(self, current):
            return True
        key = (current.x, current.y)
        if key in seen or not _on_map(c, current) or not c.is_in_vision(current):
            return False
        seen.add(key)
        bid = c.get_tile_building_id(current)
        if bid is None or c.get_team(bid) != c.get_team():
            return False
        etype = c.get_entity_type(bid)
        if etype not in _TRANSPORT_TYPES:
            return False
        out = _transport_output(c, current, bid)
        if out is None:
            return False
        current = out
    return False


def _escape_unproductive_transport_chain(self: Axioniter, c: Controller) -> bool:
    build_id = c.get_tile_building_id(self.current_pos)
    if build_id is None or c.get_team(build_id) != c.get_team():
        return False
    entity_type = c.get_entity_type(build_id)
    if entity_type not in _TRANSPORT_TYPES:
        return False
    if _chain_reaches_return_goal(self, c, self.current_pos):
        return False

    goal = self.return_target_pos or self.core_pos
    candidates: list[Direction] = []
    for direction in DIRECTIONS_4:
        pos = self.current_pos.add(direction)
        if not _on_map(c, pos) or not c.is_in_vision(pos):
            continue
        bid = c.get_tile_building_id(pos)
        if bid is not None:
            etype = c.get_entity_type(bid)
            if c.get_team(bid) != c.get_team() or etype in (
                EntityType.HARVESTER,
                EntityType.FOUNDRY,
            ):
                continue
            if etype in _TRANSPORT_TYPES and not _chain_reaches_return_goal(
                self, c, pos
            ):
                continue
        if c.can_move(direction):
            candidates.append(direction)
    candidates.sort(key=lambda d: self.current_pos.add(d).distance_squared(goal))
    if not candidates:
        return False
    c.move(candidates[0])
    self.return_chain_cursor = None
    self.return_planner = None
    self.return_next_dir = None
    return True


def _escape_dead_end_transport_tile(self: Axioniter, c: Controller) -> bool:
    build_id = c.get_tile_building_id(self.current_pos)
    if build_id is None or c.get_team(build_id) != c.get_team():
        return False
    entity_type = c.get_entity_type(build_id)
    if entity_type not in _TRANSPORT_TYPES:
        return False
    out = _transport_output(c, self.current_pos, build_id)
    if out is not None and _on_map(c, out) and c.is_in_vision(out):
        out_bid = c.get_tile_building_id(out)
        if _at_return_goal(self, out):
            return False
        if (
            out_bid is not None
            and c.get_team(out_bid) == c.get_team()
            and c.get_entity_type(out_bid)
            in _TRANSPORT_TYPES
            | {EntityType.CORE, EntityType.FOUNDRY, EntityType.HARVESTER}
        ):
            return False

    goal = self.return_target_pos or self.core_pos
    candidates: list[Direction] = []
    for direction in DIRECTIONS_4:
        pos = self.current_pos.add(direction)
        if not _on_map(c, pos) or not c.is_in_vision(pos):
            continue
        bid = c.get_tile_building_id(pos)
        if bid is not None:
            etype = c.get_entity_type(bid)
            if c.get_team(bid) != c.get_team() or etype in (
                EntityType.HARVESTER,
                EntityType.FOUNDRY,
            ):
                continue
            if etype in _TRANSPORT_TYPES:
                out2 = _transport_output(c, pos, bid)
                if out2 is None or not _on_map(c, out2):
                    continue
        if c.can_move(direction):
            candidates.append(direction)
    candidates.sort(key=lambda d: self.current_pos.add(d).distance_squared(goal))
    if not candidates:
        return False
    c.move(candidates[0])
    self.return_planner = None
    self.return_next_dir = None
    return True


def _ensure_return_planner(self: Axioniter, c: Controller):
    goal = self.return_target_pos
    if goal is None:
        return None
    goal_key = (goal.x, goal.y)
    if self.return_planner_goal != goal_key:
        self.return_planner = None
        self.return_planner_goal = goal_key
    if self.return_planner is None and self.environment_map is not None:
        self.return_planner = DStarLite(
            self.environment_map,
            goal.x,
            goal.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
            use_bridges=True,
        )
    p = self.return_planner
    if p is not None:
        p.set_dynamic_blockers(
            _return_dynamic_blockers(self, c),
            DSTAR_CPU_DEADLINE_US,
            c.get_cpu_time_elapsed,
        )
        p.notify_map_changes(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
    return p


def _planner_step_at(self: Axioniter, c: Controller, pos: Position) -> Direction | None:
    p = _ensure_return_planner(self, c)
    if p is None:
        return None
    p.set_position(pos.x, pos.y)
    step = p.step()
    return None if step == Direction.CENTRE else step


def _clear_return_tile(_: Axioniter, c: Controller, pos: Position) -> bool:
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


def _try_satisfy_remote_return_conveyor(
    self: Axioniter, c: Controller, pos: Position, direction: Direction | None
) -> bool:
    if direction is None or direction not in DIRECTIONS_4:
        return False
    if self.current_pos.distance_squared(pos) > 2:
        return False

    bid = c.get_tile_building_id(pos)
    if bid is not None:
        etype = c.get_entity_type(bid)
        allied = c.get_team(bid) == c.get_team()
        if (
            allied
            and etype == EntityType.CONVEYOR
            and c.get_direction(bid) == direction
        ):
            return True
        if etype == EntityType.MARKER and c.can_destroy(pos):
            c.destroy(pos)
            bid = None
        elif etype == EntityType.ROAD and c.can_destroy(pos):
            c.destroy(pos)
            bid = None
        else:
            return False

    if c.get_tile_env(pos) == Environment.EMPTY:
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if self.ti < conveyor_cost_ti:
            return False
    if c.can_build_conveyor(pos, direction):
        c.build_conveyor(pos, direction)

    bid = c.get_tile_building_id(pos)
    return (
        bid is not None
        and c.get_team(bid) == c.get_team()
        and c.get_entity_type(bid) == EntityType.CONVEYOR
        and c.get_direction(bid) == direction
    )


def _remote_build_spots(
    self: Axioniter, c: Controller, target: Position
) -> list[Position]:
    env = self.environment_map
    if env is None:
        return []

    spots: list[Position] = []
    for dx, dy in _ACTION_RADIUS_OFFSETS:
        pos = Position(target.x + dx, target.y + dy)
        if not env.in_bounds(pos.x, pos.y):
            continue
        if (1 << env.tile(pos.x, pos.y)) & _RETURN_BLOCK_MASK:
            continue
        if c.is_in_vision(pos):
            bot_id = c.get_tile_builder_bot_id(pos)
            if bot_id is not None and bot_id != c.get_id():
                continue
            bid = c.get_tile_building_id(pos)
            if bid is not None and c.get_entity_type(bid) not in (
                EntityType.MARKER,
                EntityType.ROAD,
                EntityType.CONVEYOR,
                EntityType.BRIDGE,
                EntityType.SPLITTER,
                EntityType.CORE,
            ):
                continue
        spots.append(pos)

    goal = self.return_target_pos or self.current_pos
    spots.sort(
        key=lambda p: (self.current_pos.distance_squared(p), p.distance_squared(goal))
    )
    return spots


def _move_toward_remote_build_spot(
    self: Axioniter,
    c: Controller,
    target: Position,
    *,
    allow_build_road: bool,
) -> bool:
    if self.current_pos.distance_squared(target) <= 2:
        return True
    env = self.environment_map
    if env is None:
        return False

    blockers = _body_dynamic_blockers(self, c)
    for goal in _remote_build_spots(self, c, target):
        if _same_pos(goal, self.current_pos):
            return True
        planner = DStarLite(
            env,
            goal.x,
            goal.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
        )
        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner.set_dynamic_blockers(
            blockers, DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed
        )
        planner.notify_map_changes(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
        move_dir = planner.step(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
        if move_dir is None or move_dir == Direction.CENTRE:
            continue

        move_pos = self.current_pos.add(move_dir)
        if c.get_tile_builder_bot_id(move_pos) is not None:
            continue

        build_id = c.get_tile_building_id(move_pos)
        if (
            build_id is not None
            and c.get_entity_type(build_id) == EntityType.MARKER
            and c.can_destroy(move_pos)
        ):
            c.destroy(move_pos)
            return True

        if not c.can_move(move_dir):
            if (
                not allow_build_road
                or c.get_tile_env(move_pos) != Environment.EMPTY
                or not c.can_build_road(move_pos)
            ):
                continue
            c.build_road(move_pos)

        if c.can_move(move_dir):
            c.move(move_dir)
            return True

    return False


def _chain_step_from(
    self: Axioniter, c: Controller, cursor: Position
) -> Direction | None:
    goal = self.return_target_pos
    if goal is None:
        return None
    if _same_pos(cursor, goal):
        return None
    step = _planner_step_at(self, c, cursor) or cursor.direction_to(goal)
    if step is None or step == Direction.CENTRE:
        return None
    if step in DIRECTIONS_4:
        return step
    return get_direction_4(cursor, goal)


def _handle_remote_return_chain(self: Axioniter, c: Controller) -> bool:
    cursor = self.return_chain_cursor
    if cursor is None:
        return False

    if _at_return_goal(self, cursor):
        _complete_return(self, c)
        return True

    chain_dir = _chain_step_from(self, c, cursor)
    if chain_dir is None:
        return True
    target = cursor.add(chain_dir)

    if _at_return_goal(self, target):
        _complete_return(self, c)
        return True

    if self.current_pos.distance_squared(target) <= 2:
        next_dir = _chain_step_from(self, c, target)
        if _try_satisfy_remote_return_conveyor(self, c, target, next_dir):
            self.return_chain_cursor = target
            if next_dir is not None:
                _move_toward_remote_build_spot(
                    self, c, target.add(next_dir), allow_build_road=False
                )
        return True

    _move_toward_remote_build_spot(self, c, target, allow_build_road=True)
    return True


def _allied_transport_at(c: Controller, pos: Position) -> int | None:
    if not _on_map(c, pos) or not c.is_in_vision(pos):
        return None
    bid = c.get_tile_building_id(pos)
    if bid is None or c.get_team(bid) != c.get_team():
        return None
    if c.get_entity_type(bid) not in _TRANSPORT_TYPES:
        return None
    return bid


def _transport_output(c: Controller, pos: Position, bid: int) -> Position | None:
    etype = c.get_entity_type(bid)
    if etype == EntityType.BRIDGE:
        try:
            return c.get_bridge_target(bid)
        except Exception:
            return None
    try:
        direction = c.get_direction(bid)
    except Exception:
        return None
    if direction is None or direction == Direction.CENTRE:
        return None
    if etype == EntityType.SPLITTER and direction not in DIRECTIONS_4:
        return None
    return pos.add(direction)


def _update_chain_memory(self: Axioniter, c: Controller) -> None:
    """Remember nearby allied transport so axionite can join real titanium chains."""
    now = c.get_current_round()
    stale_before = now - _CHAIN_MEMORY_TTL
    for key, entry in list(self.chain_memory.items()):
        if entry.get("round", 0) < stale_before:
            self.chain_memory.pop(key, None)

    for pos in c.get_nearby_tiles():
        bid = _allied_transport_at(c, pos)
        if bid is None:
            continue

        stored = c.get_stored_resource(bid)
        entry = self.chain_memory.get((pos.x, pos.y), {})
        if stored == ResourceType.TITANIUM:
            entry["last_titanium_round"] = now
        entry.update(
            {
                "round": now,
                "type": c.get_entity_type(bid),
                "out": (
                    None
                    if (out := _transport_output(c, pos, bid)) is None
                    else (out.x, out.y)
                ),
                "resource": stored,
                "resource_id": c.get_stored_resource_id(bid),
                "dist_core": max(
                    abs(pos.x - self.core_pos.x), abs(pos.y - self.core_pos.y)
                ),
            }
        )
        self.chain_memory[(pos.x, pos.y)] = entry


def _on_map(c: Controller, pos: Position) -> bool:
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def _flows_into(
    c: Controller, src: Position, src_id: int, etype: EntityType, target: Position
) -> bool:
    facing = c.get_direction(src_id)
    if facing == Direction.CENTRE:
        return False
    if etype == EntityType.SPLITTER:
        out_dirs = (
            facing,
            facing.rotate_left().rotate_left(),
            facing.rotate_right().rotate_right(),
        )
    else:
        out_dirs = (facing,)
    for out_dir in out_dirs:
        out = src.add(out_dir)
        if out.x == target.x and out.y == target.y:
            return True
    return False


def _foundry_has_outbound_flow(c: Controller, foundry_pos: Position) -> bool:
    team = c.get_team()
    for direction in DIRECTIONS_4:
        adj = foundry_pos.add(direction)
        if not _on_map(c, adj) or not c.is_in_vision(adj):
            continue
        bid = c.get_tile_building_id(adj)
        if bid is None or c.get_team(bid) != team:
            continue
        etype = c.get_entity_type(bid)
        if etype not in _TRANSPORT_TYPES:
            continue
        if etype == EntityType.BRIDGE:
            try:
                target = c.get_bridge_target(bid)
            except Exception:
                continue
            if target is not None and target != foundry_pos:
                return True
            continue
        if not _flows_into(c, adj, bid, etype, foundry_pos):
            return True
    return False


def _pick_foundry_outbound_start(
    self: Axioniter, c: Controller, foundry_pos: Position
) -> Position | None:
    candidates: list[Position] = []
    for direction in DIRECTIONS_4:
        adj = foundry_pos.add(direction)
        if not _on_map(c, adj):
            continue
        if adj == self.current_pos:
            continue
        if c.is_in_vision(adj):
            bot_id = c.get_tile_builder_bot_id(adj)
            if bot_id is not None and bot_id != c.get_id():
                continue
            bid = c.get_tile_building_id(adj)
            if bid is not None:
                etype = c.get_entity_type(bid)
                if etype == EntityType.MARKER:
                    candidates.append(adj)
                    continue
                if c.get_team(bid) != c.get_team():
                    continue
                if etype not in {EntityType.ROAD, EntityType.CONVEYOR}:
                    continue
        candidates.append(adj)

    if not candidates:
        return None
    candidates.sort(key=lambda p: p.distance_squared(self.core_pos))
    return candidates[0]


def _move_to_outbound_start(self: Axioniter, c: Controller, target: Position) -> bool:
    if _same_pos(self.current_pos, target):
        return True
    env = self.environment_map
    if env is None:
        move_dir = get_direction_4(self.current_pos, target)
    else:
        planner = DStarLite(
            env,
            target.x,
            target.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
        )
        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner.set_dynamic_blockers(
            _body_dynamic_blockers(self, c),
            DSTAR_CPU_DEADLINE_US,
            c.get_cpu_time_elapsed,
        )
        planner.notify_map_changes(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
        move_dir = planner.step(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
        if move_dir is None or move_dir == Direction.CENTRE:
            move_dir = get_direction_4(self.current_pos, target)

    move_pos = self.current_pos.add(move_dir)
    bid = c.get_tile_building_id(move_pos)
    if (
        bid is not None
        and c.get_entity_type(bid) == EntityType.MARKER
        and c.can_destroy(move_pos)
    ):
        c.destroy(move_pos)
        return False
    if (
        not c.can_move(move_dir)
        and c.get_tile_env(move_pos) == Environment.EMPTY
        and c.can_build_road(move_pos)
    ):
        c.build_road(move_pos)
    if c.can_move(move_dir):
        c.move(move_dir)
    return False


def _finish_foundry_outbound(self: Axioniter) -> None:
    self.outbound_foundry_pos = None
    self.outbound_start_pos = None
    self.outbound_started = False
    self.harvester_pos = None
    self.returning_from_axionite = False
    self.target_pos = None
    self.seek_target_is_ore = False
    self.blacklisted_ores.clear()
    self.blacklisted_seek_targets.clear()
    self.state = type(self.state).SEEK
    _reset_return_state(self)


def _handle_foundry_outbound(self: Axioniter, c: Controller) -> bool:
    foundry_pos = self.outbound_foundry_pos
    if foundry_pos is None:
        return False

    if (
        reached_core(self.current_pos, self.core_pos)
        and self.bridge_jump_target is None
        and not self.just_placed
    ):
        _finish_foundry_outbound(self)
        return True

    if self.outbound_start_pos is None:
        self.outbound_start_pos = _pick_foundry_outbound_start(self, c, foundry_pos)
        if self.outbound_start_pos is None:
            return True

    if (
        not _same_pos(self.current_pos, self.outbound_start_pos)
        and not self.outbound_started
    ):
        _move_to_outbound_start(self, c, self.outbound_start_pos)
        return True

    if not self.outbound_started:
        self.harvester_pos = foundry_pos
        self.just_placed = True
        self.returning_from_axionite = False
        _reset_return_state(self)
        self.outbound_started = True

    if _attack_enemy_under_bot(self, c):
        return True
    harvester_self = cast(Any, self)
    if _harvester_handle_post_bridge_conveyor(harvester_self, c):
        return True

    _harvester_build_return_step(harvester_self, c)
    return True


def _at_return_goal(self: Axioniter, pos: Position) -> bool:
    return _same_pos(pos, self.return_target_pos)


def _finish_foundry_return(
    self: Axioniter, c: Controller, foundry_pos: Position
) -> None:
    self.foundry_curr_placed = True
    self.foundry_prev_placed = True
    self.foundry_placed_round = c.get_current_round()
    self.target_pos = None
    self.seek_target_is_ore = False
    self.blacklisted_ores.clear()
    self.blacklisted_seek_targets.clear()
    self.returning_from_axionite = False
    if _foundry_has_outbound_flow(c, foundry_pos):
        self.harvester_pos = None
        self.state = type(self.state).SEEK
        _reset_return_state(self)
        return

    self.outbound_foundry_pos = foundry_pos
    self.outbound_start_pos = None
    self.outbound_started = False
    self.harvester_pos = foundry_pos
    self.just_placed = False
    self.state = type(self.state).RETURN
    _reset_return_state(self)


def _feed_conveyor_ready(self: Axioniter, c: Controller, goal: Position) -> bool:
    if _same_pos(self.current_pos, goal):
        return False

    feed_dir = self.current_pos.direction_to(goal)
    if feed_dir not in DIRECTIONS_4:
        return False

    bid = c.get_tile_building_id(self.current_pos)
    if bid is not None:
        etype = c.get_entity_type(bid)
        allied = c.get_team(bid) == c.get_team()
        if allied and etype == EntityType.CONVEYOR and c.get_direction(bid) == feed_dir:
            return True
        if etype not in _FEED_REPLACEABLE_TYPES:
            return False
        if etype != EntityType.MARKER and not allied:
            return False
        foundry_cost_ti, _ = c.get_foundry_cost()
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        ti, _ = c.get_global_resources()
        if ti < foundry_cost_ti + conveyor_cost_ti:
            return False
        if not c.can_destroy(self.current_pos):
            return False
        c.destroy(self.current_pos)
        return False

    if c.get_tile_env(self.current_pos) != Environment.EMPTY:
        return False

    foundry_cost_ti, _ = c.get_foundry_cost()
    conveyor_cost_ti, _ = c.get_conveyor_cost()
    ti, _ = c.get_global_resources()
    if ti < foundry_cost_ti + conveyor_cost_ti:
        return False
    if c.can_build_conveyor(self.current_pos, feed_dir):
        c.build_conveyor(self.current_pos, feed_dir)
    return False


def _try_place_foundry(self: Axioniter, c: Controller, goal: Position) -> bool:
    if self.current_pos.distance_squared(goal) > 2:
        return False

    bid = c.get_tile_building_id(goal)
    if (
        bid is not None
        and c.get_entity_type(bid) == EntityType.FOUNDRY
        and c.get_team(bid) == c.get_team()
    ):
        _finish_foundry_return(self, c, goal)
        return True

    if not _feed_conveyor_ready(self, c, goal):
        return True

    foundry_cost_ti, _ = c.get_foundry_cost()
    ti, _ = c.get_global_resources()
    if ti < foundry_cost_ti:
        return True

    if bid is not None:
        etype = c.get_entity_type(bid)
        if etype == EntityType.MARKER:
            if c.can_build_foundry(goal):
                c.build_foundry(goal)
                _finish_foundry_return(self, c, goal)
            return True
        if c.get_team(bid) != c.get_team() or etype not in _FOUNDRY_REPLACEABLE_TYPES:
            return True
        if not c.can_destroy(goal):
            return True
        c.destroy(goal)
        if c.can_build_foundry(goal):
            c.build_foundry(goal)
            _finish_foundry_return(self, c, goal)
        return True

    if c.get_tile_env(goal) != Environment.EMPTY:
        return True
    if c.can_build_foundry(goal):
        c.build_foundry(goal)
        _finish_foundry_return(self, c, goal)
    return True


def _complete_return(self: Axioniter, c: Controller) -> None:
    goal = self.return_target_pos
    if goal is None:
        return
    _try_place_foundry(self, c, goal)


def _try_chain_shortcut(self: Axioniter, c: Controller) -> bool:
    return False


def _next_dir_after_move(
    self: Axioniter, c: Controller, move_dir: Direction
) -> Direction | None:
    """Conveyor direction to place on the tile we're about to step onto."""
    move_pos = self.current_pos.add(move_dir)
    if _at_return_goal(self, move_pos):
        return None
    goal = self.return_target_pos
    if goal is None:
        return None
    follow_dir = _planner_step_at(self, c, move_pos) or move_pos.direction_to(goal)
    if follow_dir is None or follow_dir == Direction.CENTRE:
        return None
    if follow_dir in DIRECTIONS_4:
        return follow_dir
    return get_direction_4(move_pos, move_pos.add(follow_dir))


def _handle_post_bridge_conveyor(self: Axioniter, c: Controller) -> bool:
    """Place conveyor on current tile after crossing a bridge. Returns True while consuming the turn."""
    if not self.post_bridge_conveyor:
        return False

    if _at_return_goal(self, self.current_pos):
        _complete_return(self, c)
        self.post_bridge_conveyor = False
        return True

    conveyor_dir = _planner_step_at(self, c, self.current_pos)
    key = ("post_bridge", self.current_pos.x, self.current_pos.y)
    if conveyor_dir is None:
        _post_bridge_fail(self, key)
        return True
    if conveyor_dir == Direction.CENTRE or conveyor_dir not in DIRECTIONS_4:
        _post_bridge_fail(self, key)
        return True

    bid = c.get_tile_building_id(self.current_pos)
    if bid is not None:
        etype = c.get_entity_type(bid)
        allied = c.get_team(bid) == c.get_team()
        if allied and etype == EntityType.CONVEYOR:
            if c.get_direction(bid) == conveyor_dir:
                self.return_next_dir = conveyor_dir
                self.post_bridge_conveyor = False
                self.return_bridge_fail_counts.pop(key, None)
            elif c.can_destroy(self.current_pos):
                c.destroy(self.current_pos)
            return True
        if etype == EntityType.ROAD:
            if c.get_tile_env(self.current_pos) == Environment.EMPTY and c.can_destroy(
                self.current_pos
            ):
                c.destroy(self.current_pos)
            else:
                self.return_next_dir = conveyor_dir
                self.post_bridge_conveyor = False
            return True

    if _clear_return_tile(self, c, self.current_pos):
        tile_empty = c.get_tile_env(self.current_pos) == Environment.EMPTY
        ti, _ = c.get_global_resources()
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if (
            tile_empty
            and ti >= conveyor_cost_ti
            and c.can_build_conveyor(self.current_pos, conveyor_dir)
        ):
            c.build_conveyor(self.current_pos, conveyor_dir)

        bid = c.get_tile_building_id(self.current_pos)
        connected = (
            bid is not None
            and c.get_team(bid) == c.get_team()
            and c.get_entity_type(bid)
            in (
                EntityType.CONVEYOR,
                EntityType.SPLITTER,
                EntityType.BRIDGE,
            )
        )
        if connected:
            self.return_next_dir = conveyor_dir
            self.post_bridge_conveyor = False
            self.return_bridge_fail_counts.pop(key, None)
        elif not tile_empty or ti >= conveyor_cost_ti:
            _post_bridge_fail(self, key)

    return True


def _handle_bridge_jump(self: Axioniter, c: Controller, target_pos: Position) -> bool:
    """Build a bridge to target_pos if not built yet, then walk across it."""
    bridge_pos = self.current_pos

    if self.bridge_jump_target is not None:
        if self.current_pos.distance_squared(self.bridge_jump_target) == 0:
            if _at_return_goal(self, self.current_pos):
                _complete_return(self, c)
            else:
                _clear_bridge_walk_state(self)
                self.post_bridge_conveyor = True
            return True
        return _walk_toward_bridge_target(self, c)

    bid = c.get_tile_building_id(bridge_pos)
    entity_type = c.get_entity_type(bid) if bid is not None else None
    allied = bid is not None and c.get_team(bid) == c.get_team()

    if (
        bid is not None
        and allied
        and entity_type == EntityType.BRIDGE
        and _bridge_target_matches(c, bid, target_pos)
    ):
        _start_bridge_walk(self, target_pos)
        return _walk_toward_bridge_target(self, c)

    if allied and entity_type == EntityType.BRIDGE:
        self.failed_bridge_targets.add((target_pos.x, target_pos.y))
        self.return_planner = None
        return True

    if allied and entity_type in (EntityType.ROAD, EntityType.CONVEYOR):
        ti, _ = c.get_global_resources()
        bridge_cost_ti, _ = c.get_bridge_cost()
        if ti < bridge_cost_ti or not c.can_destroy(bridge_pos):
            return True
        c.destroy(bridge_pos)

    if c.can_build_bridge(bridge_pos, target_pos):
        c.build_bridge(bridge_pos, target_pos)
        _start_bridge_walk(self, target_pos)
        return True

    ti, _ = c.get_global_resources()
    bridge_cost_ti, _ = c.get_bridge_cost()
    if ti >= bridge_cost_ti:
        key = (bridge_pos.x, bridge_pos.y, target_pos.x, target_pos.y)
        _bridge_fail(self, key)
    return True


def _ensure_bridge_target_planner(
    self: Axioniter, c: Controller, target: Position
) -> DStarLite | None:
    if self.bridge_target_planner is None and self.environment_map is not None:
        self.bridge_target_planner = DStarLite(
            self.environment_map,
            target.x,
            target.y,
            block_mask=_RETURN_BLOCK_MASK,
        )
    p = self.bridge_target_planner
    if p is not None:
        p.set_position(self.current_pos.x, self.current_pos.y)
        p.set_dynamic_blockers(
            _body_dynamic_blockers(self, c),
            DSTAR_CPU_DEADLINE_US,
            c.get_cpu_time_elapsed,
        )
        p.notify_map_changes(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
    return p


_BRIDGE_WALKABLE_TYPES = (
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.ROAD,
)


def _can_execute_bridge_walk_step(c: Controller, move_dir: Direction) -> bool:
    """Return True if the bridge-walk can proceed in move_dir this round."""
    move_pos = c.get_position().add(move_dir)
    if c.can_move(move_dir):
        return True
    if not _on_map(c, move_pos):
        return False
    tile_env = c.get_tile_env(move_pos)
    build_id = c.get_tile_building_id(move_pos)
    if build_id is not None:
        etype = c.get_entity_type(build_id)
        if etype == EntityType.MARKER:
            return True
        return False
    if tile_env == Environment.EMPTY:
        return True
    return c.can_build_road(move_pos)


def _walk_toward_bridge_target(self: Axioniter, c: Controller) -> bool:
    target = self.bridge_jump_target
    if target is None:
        return False

    if _at_return_goal(self, target):
        if _at_return_goal(self, self.current_pos):
            _complete_return(self, c)
            return True

    if _same_pos(self.current_pos, target):
        if _at_return_goal(self, target):
            _complete_return(self, c)
            return True
        _clear_bridge_walk_state(self)
        self.post_bridge_conveyor = True
        return True

    p = _ensure_bridge_target_planner(self, c, target)
    move_dir = (
        p.step(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed) if p is not None else None
    )
    if move_dir is None or move_dir == Direction.CENTRE:
        if p is not None and p.planning_pending():
            return True
        key = (
            "bridge_walk",
            self.current_pos.x,
            self.current_pos.y,
            target.x,
            target.y,
        )
        _bridge_fail(self, key)
        return True

    if not _can_execute_bridge_walk_step(c, move_dir):
        key = (
            "bridge_walk",
            self.current_pos.x,
            self.current_pos.y,
            target.x,
            target.y,
        )
        _bridge_fail(self, key)
        return True

    move_pos = self.current_pos.add(move_dir)
    if _at_return_goal(self, move_pos):
        _complete_return(self, c)
        return True

    build_id = c.get_tile_building_id(move_pos)
    if (
        build_id is not None
        and c.get_entity_type(build_id) == EntityType.MARKER
        and c.can_destroy(move_pos)
    ):
        c.destroy(move_pos)
        return True

    if not c.can_move(move_dir) and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if c.can_move(move_dir):
        c.move(move_dir)
    else:
        key = (self.current_pos.x, self.current_pos.y, move_pos.x, move_pos.y)
        _bridge_fail(self, key)
    return True


def _build_return_step(self: Axioniter, c: Controller) -> bool:
    if _at_return_goal(self, self.current_pos):
        _complete_return(self, c)
        return True

    if self.bridge_jump_target is not None:
        if self.current_pos.distance_squared(self.bridge_jump_target) == 0:
            if _at_return_goal(self, self.current_pos):
                _complete_return(self, c)
            else:
                _clear_bridge_walk_state(self)
                self.post_bridge_conveyor = True
            return True
        return _walk_toward_bridge_target(self, c)

    if _escape_foundry_input_chain(self, c):
        return True

    if self.return_chain_cursor is not None:
        if _escape_unproductive_transport_chain(self, c):
            return True
        return _handle_remote_return_chain(self, c)

    if self.just_placed:
        goal = self.return_target_pos
        if goal is None:
            return False
        move_pos = self.current_pos
        if self.harvester_pos and is_diagonal(self.current_pos, self.harvester_pos):
            ns, ew = split_diagonal(self.current_pos, self.harvester_pos)
            m1 = self.current_pos.add(ns)  # type: ignore
            m2 = self.current_pos.add(ew)  # type: ignore
            move_pos = (
                m1 if m1.distance_squared(goal) < m2.distance_squared(goal) else m2
            )

        if _at_return_goal(self, move_pos):
            _complete_return(self, c)
            return True

        build_id = c.get_tile_building_id(move_pos)
        if (
            build_id is not None
            and c.get_entity_type(build_id) in {EntityType.ROAD, EntityType.CONVEYOR}
            and c.can_destroy(move_pos)
        ):
            c.destroy(move_pos)

        step = _planner_step_at(self, c, move_pos) or move_pos.direction_to(goal)
        if step is None or step == Direction.CENTRE:
            return False
        if step not in DIRECTIONS_4:
            step = get_direction_4(move_pos, goal)
            if step is None:
                return False

        if c.get_tile_building_id(move_pos) is None:
            conveyor_cost_ti, _ = c.get_conveyor_cost()
            if self.ti < conveyor_cost_ti:
                return False
        if c.can_build_conveyor(move_pos, step):
            c.build_conveyor(move_pos, step)

        step_dir = (
            get_direction_4(self.current_pos, move_pos)
            if self.current_pos != move_pos
            else None
        )
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

        step_xy = planner.step_xy(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
        if step_xy is not None:
            cx, cy = self.current_pos.x, self.current_pos.y
            tx, ty = step_xy
            dsq = (tx - cx) * (tx - cx) + (ty - cy) * (ty - cy)
            if dsq > 1:
                if (tx, ty) in self.failed_bridge_targets:
                    self.return_planner = None
                else:
                    return _handle_bridge_jump(self, c, Position(tx, ty))
            planner_step = self.current_pos.direction_to(Position(tx, ty))
        elif planner.planning_pending():
            return True

    if self.return_next_dir is not None:
        move_dir = self.return_next_dir
        self.return_next_dir = None
    else:
        move_dir = planner_step
        if move_dir is None or move_dir == Direction.CENTRE:
            goal = self.return_target_pos
            if goal is None:
                return False
            move_dir = self.current_pos.direction_to(goal)
        if move_dir is None or move_dir == Direction.CENTRE:
            return False
        if move_dir not in DIRECTIONS_4:
            goal = self.return_target_pos
            if goal is None:
                return False
            move_dir = get_direction_4(self.current_pos, goal)
            if move_dir is None:
                return False

    next_dir = _next_dir_after_move(self, c, move_dir)

    move_pos = self.current_pos.add(move_dir)
    if not c.can_move(move_dir) and c.get_tile_env(move_pos) != Environment.EMPTY:
        goal = self.return_target_pos
        direct_dir = (
            get_direction_4(self.current_pos, goal) if goal is not None else None
        )
        if direct_dir is not None and direct_dir != move_dir and c.can_move(direct_dir):
            self.return_planner = None
            move_dir = direct_dir
            next_dir = _next_dir_after_move(self, c, move_dir)
            move_pos = self.current_pos.add(move_dir)

    if _at_return_goal(self, move_pos):
        _complete_return(self, c)
        return True

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
    if build_id is not None and c.get_entity_type(build_id) == EntityType.CORE:
        return False

    if _enemy_walkable_at(c, move_pos):
        if not c.can_move(move_dir):
            return False
        self.return_next_dir = next_dir
        c.move(move_dir)
        return True

    move_bid = c.get_tile_building_id(move_pos)
    if (
        not c.can_move(move_dir)
        and move_bid is not None
        and c.get_team(move_bid) == c.get_team()
        and c.get_entity_type(move_bid) in _TRANSPORT_TYPES
    ):
        self.return_chain_cursor = move_pos
        self.return_next_dir = None
        if next_dir is not None:
            _move_toward_remote_build_spot(
                self, c, move_pos.add(next_dir), allow_build_road=False
            )
        return True

    bot_id = c.get_tile_builder_bot_id(move_pos)
    if bot_id is not None and bot_id != c.get_id():
        if _try_satisfy_remote_return_conveyor(self, c, move_pos, next_dir):
            self.return_chain_cursor = move_pos
            self.return_next_dir = None
            if next_dir is not None:
                _move_toward_remote_build_spot(
                    self, c, move_pos.add(next_dir), allow_build_road=False
                )
        return True

    if not c.can_move(move_dir):
        can_execute = False
        if c.get_tile_env(move_pos) == Environment.EMPTY:
            bid = c.get_tile_building_id(move_pos)
            if bid is not None and c.get_entity_type(bid) == EntityType.MARKER:
                can_execute = True
            elif c.can_build_road(move_pos):
                can_execute = True
            elif next_dir is not None:
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
