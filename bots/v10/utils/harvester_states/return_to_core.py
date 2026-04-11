from cambc import Direction, EntityType, Environment

from utils.map_memory import CORE_OWN, ORE_AX, TRAVERSABLE, UNKNOWN
from utils.movement import (
    DIRECTIONS_4,
    get_direction_4,
    get_direction_8,
    is_diagonal,
    reached_core,
    split_diagonal,
)


def _reset_return_state(self):
    """Clear temporary return execution state"""
    self.bridge_from = None
    self.return_actions.clear()
    self.post_bridge_conveyor = False


def _is_return_tile_usable(self, c, pos) -> bool:
    """Check whether a split return tile is locally safe to use"""
    if reached_core(pos, self.core_pos):
        return True

    if not c.is_in_vision(pos):
        if not (0 <= pos.x < self.memory._w and 0 <= pos.y < self.memory._h):
            return False
        return self.memory._tiles[pos.y][pos.x] in (TRAVERSABLE, ORE_AX, CORE_OWN, UNKNOWN)

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
    return entity_type in (EntityType.CONVEYOR, EntityType.BRIDGE)


def _clear_return_tile(self, c, pos) -> bool:
    """Remove temporary structures before placing return infrastructure"""
    build_id = c.get_tile_building_id(pos)
    if build_id is None:
        return True

    entity_type = c.get_entity_type(build_id)
    if entity_type == EntityType.ROAD and c.can_destroy(pos):
        c.destroy(pos)
        return True
    if entity_type == EntityType.CORE:
        return True
    if c.get_team(build_id) != c.get_team():
        return False
    return entity_type in (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.CORE)


def _choose_diagonal_split(self, c, move_dir: Direction) -> list[Direction] | None:
    """Expand one diagonal return edge into a committed cardinal pair"""
    ns, ew = split_diagonal(self.current_pos, self.current_pos.add(move_dir))
    if ns is None or ew is None:
        return None

    preferred = get_direction_4(self.current_pos, self.core_pos)
    options = [(ns, ew), (ew, ns)]
    if preferred == ew:
        options.reverse()

    # Prefer the cardinal component that already matches the simple inward move.
    for first, second in options:
        first_pos = self.current_pos.add(first)
        first_usable = _is_return_tile_usable(self, c, first_pos)
        if not first_usable:
            continue

        if reached_core(first_pos, self.core_pos):
            if c.can_move(first):
                return [first]
            continue

        # Only start a diagonal if we can commit the whole 2-cardinal sequence.
        first_exec = _can_execute_return_step(self, c, first, second)
        if not first_exec:
            continue

        second_pos = first_pos.add(second)
        second_usable = _is_return_tile_usable(self, c, second_pos)
        if not second_usable:
            continue

        return [first, second]

    return None


def _can_execute_return_step(self, c, move_dir: Direction, next_move_dir: Direction | None) -> bool:
    """Check whether the next return step can be realized this turn"""
    if c.can_move(move_dir):
        return True

    if next_move_dir is None:
        return False

    move_pos = self.current_pos.add(move_dir)
    return c.can_build_conveyor(move_pos, next_move_dir)


def _plan_blocked_return_fallback(
    self, c, move_dir: Direction
) -> tuple[list[Direction] | None, Direction | None]:
    """Prefer bridge-oriented fallback over local detours"""
    if move_dir not in DIRECTIONS_4:
        split = _choose_diagonal_split(self, c, move_dir)
        if split is not None:
            return split, None
        return None, move_dir

    # could make non deterministic sometimes
    diagonal_dir = self.current_pos.direction_to(self.core_pos)
    if diagonal_dir not in DIRECTIONS_4 and diagonal_dir != Direction.CENTRE:
        return None, diagonal_dir

    return None, None


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

    conveyor_dir = get_direction_4(move_pos, self.core_pos)

    if c.can_build_conveyor(move_pos, conveyor_dir):
        c.build_conveyor(move_pos, conveyor_dir)

    if self.current_pos != move_pos:
        step_dir = get_direction_4(self.current_pos, move_pos)
        if c.can_move(step_dir):
            c.move(step_dir)
            return True
        return False

    return True


def _build_return_step(self, c) -> bool:
    """Lay a return path using split cardinals first, then bridge fallback"""
    if not self.return_actions:
        move_dir = get_direction_8(self.current_pos, self.core_pos)
        if move_dir is None:
            return False

        if move_dir in DIRECTIONS_4:
            self.return_actions = [move_dir]
        else:
            split = _choose_diagonal_split(self, c, move_dir)
            if split is not None:
                self.return_actions = split
            else:
                return _handle_return_diagonal_step(self, c, move_dir)

    move_dir = self.return_actions[0]
    move_pos = self.current_pos.add(move_dir)

    next_move_dir = (
        self.return_actions[1]
        if len(self.return_actions) > 1
        else get_direction_4(move_pos, self.core_pos)
    )
    if next_move_dir is None:
        return False

    if not _can_execute_return_step(self, c, move_dir, next_move_dir):
        fallback_actions, bridge_dir = _plan_blocked_return_fallback(self, c, move_dir)
        if fallback_actions is not None:
            self.return_actions = fallback_actions
            move_dir = self.return_actions[0]
            move_pos = self.current_pos.add(move_dir)
            next_move_dir = (
                self.return_actions[1]
                if len(self.return_actions) > 1
                else get_direction_4(move_pos, self.core_pos)
            )
        elif bridge_dir is not None:
            return _handle_return_diagonal_step(self, c, bridge_dir)
        else:
            self.return_actions.clear()
            return False

    if reached_core(move_pos, self.core_pos):
        if c.can_move(move_dir):
            self.return_actions.pop(0)
            c.move(move_dir)
            return True
        self.return_actions.clear()
        return False

    build_id = c.get_tile_building_id(move_pos)
    if build_id is not None and c.get_entity_type(build_id) == EntityType.CORE:
        if c.can_move(move_dir):
            self.return_actions.pop(0)
            c.move(move_dir)
            return True
        self.return_actions.clear()
        return False

    if not _clear_return_tile(self, c, move_pos):
        return False

    if c.can_build_conveyor(move_pos, next_move_dir):
        c.build_conveyor(move_pos, next_move_dir)

    if c.can_move(move_dir):
        self.return_actions.pop(0)
        c.move(move_dir)
        return True

    self.return_actions.clear()
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

    bridge_pos = self.bridge_from
    build_id = c.get_tile_building_id(bridge_pos)
    entity_type = c.get_entity_type(build_id) if build_id is not None else None
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

    if not _clear_return_tile(self, c, self.current_pos):
        return False

    if (
        c.get_tile_env(self.current_pos) == Environment.EMPTY
        and c.can_build_conveyor(self.current_pos, conveyor_dir)
    ):
        c.build_conveyor(self.current_pos, conveyor_dir)

    self.post_bridge_conveyor = False
    return True


def _return(self, c):
    """Lay conveyors back to the core"""
    self._update_foundry_flag(c)

    if self.just_placed:
        if _build_first_connector(self, c):
            self.just_placed = False
        return

    if reached_core(self.current_pos, self.core_pos):
        self.state = type(self.state).SEEK
        self.target_pos = None
        self.harvester_pos = None
        _reset_return_state(self)
        return

    if self.bridge_from is not None:
        _handle_pending_return_bridge(self, c)
        return

    if self.post_bridge_conveyor:
        _ensure_post_bridge_conveyor(self, c)
        return

    _build_return_step(self, c)
