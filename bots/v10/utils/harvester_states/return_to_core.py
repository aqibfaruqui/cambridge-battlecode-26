from cambc import Direction, EntityType, Environment, Position

from utils.d_star import DStarLite, _RETURN_BLOCK_MASK
from utils.map_memory import CORE_OWN, ORE_AX, TRAVERSABLE, UNKNOWN
from utils.movement import (
    DIRECTIONS_4,
    get_direction_4,
    is_diagonal,
    reached_core,
    split_diagonal,
)
from utils.network_connectivity import compute_reachable_to_core


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


def _opposite_direction(direction: Direction) -> Direction | None:
    match direction:
        case Direction.NORTH:
            return Direction.SOUTH
        case Direction.SOUTH:
            return Direction.NORTH
        case Direction.EAST:
            return Direction.WEST
        case Direction.WEST:
            return Direction.EAST
        case _:
            return None


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
        back_dir = _opposite_direction(out_dir)
        if back_dir is None:
            return False
        return receiver_pos.add(back_dir) == source_pos

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
    """Clear temporary return execution state"""
    self.bridge_from = None
    self.return_pending_bridge_dir = None
    self.return_actions.clear()
    self.return_planner = None
    self.post_bridge_conveyor = False


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

def _refresh_return_planner(self, c) -> tuple[Direction | None, list[tuple[int, int]]]:
    planner = self.return_planner
    if planner is None and self.environment_map is not None:
        planner = DStarLite(
            self.environment_map,
            self.core_pos.x,
            self.core_pos.y,
            block_mask=_RETURN_BLOCK_MASK,
        )
        self.return_planner = planner

    if planner is None:
        return None, []

    planner.set_position(self.current_pos.x, self.current_pos.y)
    planner.set_dynamic_blockers(_return_dynamic_blockers(c))
    planner.notify_map_changes()

    return planner.step(), planner.extract_path()

def _planner_step_at(self, c, pos: Position) -> Direction | None:
    planner = self.return_planner
    if planner is None and self.environment_map is not None:
        planner = DStarLite(
            self.environment_map,
            self.core_pos.x,
            self.core_pos.y,
            block_mask=_RETURN_BLOCK_MASK,
        )
        self.return_planner = planner

    if planner is None:
        return None

    planner.set_position(pos.x, pos.y)
    planner.set_dynamic_blockers(_return_dynamic_blockers(c))
    planner.notify_map_changes()
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


def _can_step_from_tile(self, c, origin: Position, step_dir: Direction) -> bool:
    target = origin.add(step_dir)
    if not _is_return_tile_usable(self, c, target):
        return False
    return True


def _can_realize_step_from_tile(
    self,
    c,
    origin: Position,
    first: Direction,
    second: Direction | None = None,
) -> bool:
    # If we're evaluating from the current tile, enforce immediate executability.
    if origin == self.current_pos:
        first_pos = origin.add(first)
        can_seed = second is not None and c.can_build_conveyor(first_pos, second)
        if not (c.can_move(first) or can_seed):
            return False

    if not _can_step_from_tile(self, c, origin, first):
        return False
    if second is None:
        return True
    first_pos = origin.add(first)
    return _can_step_from_tile(self, c, first_pos, second)


def _resolve_diagonal_plan(
    self,
    c,
    origin: Position,
    move_dir: Direction,
) -> tuple[str, list[Direction] | None, Direction | None]:
    """Choose split-first, bridge-when-needed for a diagonal intent."""
    ordered = _ordered_split(self, origin, move_dir)
    if ordered is None:
        return "none", None, None

    options = [(ordered[0], ordered[1]), (ordered[1], ordered[0])]
    chosen: list[Direction] | None = None
    for first, second in options:
        first_pos = origin.add(first)
        if reached_core(first_pos, self.core_pos):
            if _can_realize_step_from_tile(self, c, origin, first, None):
                chosen = [first]
                break
            continue

        if not _can_realize_step_from_tile(self, c, origin, first, second):
            continue
        chosen = [first, second]
        break

    if chosen is not None:
        return "split", chosen, None

    # Bridge fallback is only meaningful from the current tile.
    if origin == self.current_pos and c.can_move(move_dir):
        return "bridge_now", None, move_dir

    # Continuation fallback: execute current cardinal move this tick, then bridge diagonally next tick.
    if origin != self.current_pos and _can_step_from_tile(self, c, origin, move_dir):
        return "bridge_later", None, move_dir

    return "none", None, None


def _resolve_next_after_move(
    self,
    c,
    move_dir: Direction,
    queued_followup: list[Direction],
    planner_path: list[tuple[int, int]] | None = None,
) -> tuple[Direction | None, list[Direction], Direction | None]:
    move_pos = self.current_pos.add(move_dir)

    if queued_followup:
        next_dir = queued_followup[0]
        actions = [move_dir, *queued_followup]
        return next_dir, actions, None

    follow_dir = None
    follow_dir_source = "unknown"
    if planner_path is not None and len(planner_path) >= 3:
        p0 = planner_path[0]
        p1 = planner_path[1]
        p2 = planner_path[2]
        if p0 == (self.current_pos.x, self.current_pos.y) and p1 == (move_pos.x, move_pos.y):
            follow_dir = move_pos.direction_to(Position(p2[0], p2[1]))
            follow_dir_source = "planner_path"

    if follow_dir is None:
        follow_dir = _planner_step_at(self, c, move_pos)
        if follow_dir is not None:
            follow_dir_source = "planner_step"
    if follow_dir is None:
        follow_dir = move_pos.direction_to(self.core_pos)
        follow_dir_source = "core_fallback"
    if follow_dir is None or follow_dir == Direction.CENTRE:
        return None, [move_dir], None

    if follow_dir in DIRECTIONS_4:
        return follow_dir, [move_dir], None

    kind, split, bridge_dir = _resolve_diagonal_plan(self, c, move_pos, follow_dir)
    if kind == "bridge_later" and bridge_dir is not None:
        return None, [move_dir], bridge_dir

    if kind != "split" or split is None or len(split) == 0:
        return None, [move_dir], None
    actions = [move_dir, *split]
    return split[0], actions, None


def _resolve_return_intent(
    self,
    c,
    planner_step: Direction | None,
    planner_path: list[tuple[int, int]] | None = None,
) -> tuple[Direction | None, Direction | None, list[Direction], Direction | None, Direction | None]:
    move_dir = None
    queued_followup: list[Direction] = []

    if self.return_actions:
        move_dir = self.return_actions[0]
        queued_followup = self.return_actions[1:]
    else:
        move_dir = planner_step
        if move_dir is None or move_dir == Direction.CENTRE:
            move_dir = self.current_pos.direction_to(self.core_pos)
        if move_dir is None or move_dir == Direction.CENTRE:
            return None, None, [], None

        if move_dir not in DIRECTIONS_4:
            kind, split, bridge_dir = _resolve_diagonal_plan(self, c, self.current_pos, move_dir)
            if kind == "bridge_now" and bridge_dir is not None:
                return None, None, [], bridge_dir, None
            if kind != "split" or split is None:
                return None, None, [], move_dir, None
            move_dir = split[0]
            queued_followup = split[1:]

    next_move_dir, resolved_actions, bridge_later_dir = _resolve_next_after_move(
        self, c, move_dir, queued_followup, planner_path
    )
    if len(resolved_actions) >= 2:
        next_move_dir = resolved_actions[1]
    return move_dir, next_move_dir, resolved_actions, None, bridge_later_dir


def _connector_direction_from_planner(self, c, move_pos: Position) -> Direction | None:
    step = _planner_step_at(self, c, move_pos)
    if step is None:
        step = move_pos.direction_to(self.core_pos)
    if step is None or step == Direction.CENTRE:
        return None
    if step in DIRECTIONS_4:
        return step

    kind, split, _bridge_dir = _resolve_diagonal_plan(self, c, move_pos, step)
    if kind != "split" or split is None or len(split) == 0:
        return None
    return split[0]


def _is_return_tile_usable(self, c, pos) -> bool:
    """Check whether a split return tile is locally safe to use"""
    if reached_core(pos, self.core_pos):
        return True

    if not c.is_in_vision(pos):
        if not (0 <= pos.x < self.memory._w and 0 <= pos.y < self.memory._h):
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
    """Remove temporary structures before placing return infrastructure"""
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
    """Check whether the next return step can be realized this turn"""
    if c.can_move(move_dir):
        return True

    if next_move_dir is None:
        return False

    move_pos = self.current_pos.add(move_dir)
    return c.can_build_conveyor(move_pos, next_move_dir)


def _build_first_connector(self, c) -> bool:
    """If builder has just placed harvester, build first connecting conveyor"""
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

    conveyor_dir = _connector_direction_from_planner(self, c, move_pos)
    if conveyor_dir is None:
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


def _build_return_step(self, c) -> bool:
    """Lay a return path using split cardinals first, then bridge fallback"""
    def clear_actions_and_fail() -> bool:
        self.return_actions.clear()
        return False

    def is_core_entry_tile(pos: Position) -> bool:
        if reached_core(pos, self.core_pos):
            return True
        build_id = c.get_tile_building_id(pos)
        return build_id is not None and c.get_entity_type(build_id) == EntityType.CORE

    def try_move_and_consume(move_dir: Direction, continuation_bridge_dir: Direction | None = None) -> bool:
        if not c.can_move(move_dir):
            return clear_actions_and_fail()
        if self.return_actions:
            self.return_actions.pop(0)
        c.move(move_dir)
        if continuation_bridge_dir is not None:
            self.return_pending_bridge_dir = continuation_bridge_dir
        return True

    planner_step, _planner_path = _refresh_return_planner(self, c)

    move_dir, next_move_dir, resolved_actions, bridge_dir, bridge_later_dir = _resolve_return_intent(
        self, c, planner_step, _planner_path
    )
    if bridge_dir is not None:
        clear_actions_and_fail()
        return _handle_return_diagonal_step(self, c, bridge_dir)
    if move_dir is None:
        return clear_actions_and_fail()

    self.return_actions = resolved_actions
    if len(self.return_actions) >= 2:
        next_move_dir = self.return_actions[1]
    move_pos = self.current_pos.add(move_dir)

    continuation_bridge = bridge_later_dir is not None
    if next_move_dir is None and not continuation_bridge:
        return clear_actions_and_fail()

    if not continuation_bridge and not _can_execute_return_step(self, c, move_dir, next_move_dir):
        # Re-evaluate from current tile; allow bridge fallback when diagonal intent is blocked as split.
        replan_step = _planner_step_at(self, c, self.current_pos)
        if replan_step is not None and replan_step not in DIRECTIONS_4 and replan_step != Direction.CENTRE:
            kind, split, bridge_dir = _resolve_diagonal_plan(self, c, self.current_pos, replan_step)
            if kind == "bridge_now" and bridge_dir is not None:
                clear_actions_and_fail()
                return _handle_return_diagonal_step(self, c, bridge_dir)
            if kind == "split" and split is not None and len(split) > 0:
                move_dir = split[0]
                next_move_dir = split[1] if len(split) > 1 else None
                self.return_actions = split
                if next_move_dir is None:
                    return clear_actions_and_fail()
                move_pos = self.current_pos.add(move_dir)
                if not _can_execute_return_step(self, c, move_dir, next_move_dir):
                    return clear_actions_and_fail()
            else:
                return clear_actions_and_fail()
        else:
            return clear_actions_and_fail()

    if is_core_entry_tile(move_pos):
        return try_move_and_consume(move_dir)

    if continuation_bridge:
        # Bridge continuation still needs the immediate step to be passable.
        # If the tile is empty, pave it first so we can move this turn/next turn.
        if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
            c.build_road(move_pos)
    else:
        if not _clear_return_tile(self, c, move_pos):
            return False

        if c.can_build_conveyor(move_pos, next_move_dir):
            c.build_conveyor(move_pos, next_move_dir)
            _mark_network_reach_dirty(self)

    pending_bridge_dir = bridge_later_dir if continuation_bridge else None
    return try_move_and_consume(move_dir, pending_bridge_dir)


def _handle_pending_bridge_continuation(self, c) -> bool:
    if self.return_pending_bridge_dir is None:
        return False

    pending_dir = self.return_pending_bridge_dir
    self.return_pending_bridge_dir = None
    if _handle_return_diagonal_step(self, c, pending_dir):
        return True

    self.return_pending_bridge_dir = pending_dir
    return False


def _handle_return_diagonal_step(self, c, move_dir: Direction) -> bool:
    """Move diagonally on road, then bridge that step next turn"""
    move_pos = self.current_pos.add(move_dir)
    self.return_actions.clear()

    if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if c.can_move(move_dir):
        self.bridge_from = self.current_pos
        c.move(move_dir)
        return True

    return False


def _handle_pending_return_bridge(self, c) -> bool:
    """Replace the previous road with a bridge into the current tile"""
    if self.bridge_from is None:
        return False

    if not hasattr(self, "return_bridge_fail_counts"):
        self.return_bridge_fail_counts = {}

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
    if fails >= 3:
        # Prevent infinite freeze loops when bridge completion is permanently blocked.
        self.bridge_from = None
        self.post_bridge_conveyor = True
        self.return_bridge_fail_counts.pop(key, None)
        return True

    return False


def _ensure_post_bridge_conveyor(self, c) -> bool:
    """Turn the bridge landing tile into an inward conveyor"""
    if not self.post_bridge_conveyor:
        return False

    if reached_core(self.current_pos, self.core_pos):
        self.post_bridge_conveyor = False
        return True

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

