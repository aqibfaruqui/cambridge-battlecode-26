from heapq import heappop, heappush

from cambc import Controller, Direction, Position
from utils.movement import DIRECTIONS_8, on_map


class Pathfinding:
    def __init__(self, algorithm: str = "hybrid"):
        self.algorithm = algorithm
        self._follow_state: dict | None = None

    def reset(self):
        self._follow_state = None

    def next_direction(
        self, c: Controller, current: Position, target: Position
    ) -> Direction | None:
        if current == target:
            self.reset()
            return None

        match self.algorithm:
            # For hybrid use A* if target is in vision, otherwise use bug nav
            case "hybrid":
                if c.is_in_vision(target):
                    direction = self._a_star_direction(c, current, target)
                    if direction is not None:
                        self.reset()
                        return direction
                direction, self._follow_state = bug_nav(
                    c, current, target, self._follow_state
                )
                return direction
            case "a_star":
                self.reset()
                return self._a_star_direction(c, current, target)
            case "bug_nav":
                direction, self._follow_state = bug_nav(
                    c, current, target, self._follow_state
                )
                return direction
            case _:
                raise ValueError(f"Unknown pathfinding algorithm: {self.algorithm}")

    def _a_star_direction(
        self, c: Controller, current: Position, target: Position
    ) -> Direction | None:
        goals = self._goal_positions(c, current, target)
        if not goals:
            return None

        start_key = (current.x, current.y)
        goal_keys = {(pos.x, pos.y) for pos in goals}
        if start_key in goal_keys:
            return None

        frontier = []
        heappush(frontier, (self._goal_heuristic(current, goals), 0, start_key))
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start_key: None}
        costs = {start_key: 0}

        while frontier:
            _, cost, node = heappop(frontier)
            if cost != costs.get(node):
                continue

            if node in goal_keys:
                return self._reconstruct_direction(current, node, came_from)

            pos = Position(node[0], node[1])
            for direction in DIRECTIONS_8:
                next_pos = pos.add(direction)
                if not self._is_search_traversable(c, next_pos):
                    continue

                next_key = (next_pos.x, next_pos.y)
                next_cost = cost + 1
                if next_cost >= costs.get(next_key, float("inf")):
                    continue

                costs[next_key] = next_cost
                came_from[next_key] = node
                priority = next_cost + self._goal_heuristic(next_pos, goals)
                heappush(frontier, (priority, next_cost, next_key))

        return None

    def _goal_positions(
        self, c: Controller, current: Position, target: Position
    ) -> list[Position]:
        if self._is_search_traversable(c, target):
            return [target]

        goals = []
        for direction in DIRECTIONS_8:
            candidate = target.add(direction)
            if candidate == current or self._is_search_traversable(c, candidate):
                goals.append(candidate)
        return goals

    def _is_search_traversable(self, c: Controller, pos: Position) -> bool:
        if not on_map(c, pos) or not c.is_in_vision(pos):
            return False
        if c.is_tile_passable(pos):
            return True
        if c.is_tile_empty(pos) and c.can_build_road(pos):
            return True
        return False

    def _goal_heuristic(self, pos: Position, goals: list[Position]) -> int:
        return min(_chebyshev(pos, goal) for goal in goals)

    def _reconstruct_direction(
        self,
        start: Position,
        end_key: tuple[int, int],
        came_from: dict[tuple[int, int], tuple[int, int] | None],
    ) -> Direction | None:
        node = end_key
        previous = came_from.get(node)
        start_key = (start.x, start.y)

        while previous is not None and previous != start_key:
            node = previous
            previous = came_from.get(node)

        next_pos = Position(node[0], node[1])
        return start.direction_to(next_pos)


def _chebyshev(a: Position, b: Position):
    return max(abs(a.x - b.x), abs(a.y - b.y))


def _is_hard_blocked(c: Controller, pos: Position):
    if not on_map(c, pos):
        return True
    # Empty tiles are not passable but can be paved; don't treat those as hard walls.
    if c.is_tile_empty(pos) and c.can_build_road(pos):
        return False
    return not c.is_tile_passable(pos)


def _can_progress(c: Controller, current: Position, direction: Direction):
    next_pos = current.add(direction)
    return c.can_move(direction) or (
        on_map(c, next_pos) and c.is_tile_empty(next_pos) and c.can_build_road(next_pos)
    )


def _state_key(
    current: Position,
    target: Position,
    obstacle_pos: Position | None,
    obstacle_on_right: bool,
):
    reference = obstacle_pos if obstacle_pos is not None else target
    reference_dir = current.direction_to(reference)
    dir_idx = 0
    for idx, direction in enumerate(DIRECTIONS_8):
        if direction == reference_dir:
            dir_idx = idx
            break
    return (current.x, current.y, dir_idx, 1 if obstacle_on_right else 0)


def bug_nav(
    c: Controller,
    current: Position,
    target: Position,
    follow_state: dict | None = None,
):
    # Adapted from CamelCase v21 final Battlecode bug navigator.
    if follow_state is None or follow_state.get("target") != target:
        follow_state = {
            "target": target,
            "min_dist": float("inf"),
            "obstacle_on_right": True,
            "obstacle_pos": None,
            "visited": set(),
        }

    has_options = any(_can_progress(c, current, d) for d in DIRECTIONS_8)
    if not has_options:
        return None, follow_state

    distance = _chebyshev(current, target)
    if distance < follow_state["min_dist"]:
        follow_state["min_dist"] = distance
        follow_state["obstacle_pos"] = None
        follow_state["visited"].clear()

    obstacle_pos = follow_state["obstacle_pos"]
    if obstacle_pos is not None and not _is_hard_blocked(c, obstacle_pos):
        follow_state["obstacle_pos"] = None
        follow_state["visited"].clear()
        obstacle_pos = None

    key = _state_key(current, target, obstacle_pos, follow_state["obstacle_on_right"])
    if key in follow_state["visited"]:
        follow_state["obstacle_pos"] = None
        follow_state["visited"].clear()
        obstacle_pos = None
    else:
        follow_state["visited"].add(key)

    if obstacle_pos is None:
        forward = current.direction_to(target)
        if _can_progress(c, current, forward):
            return forward, follow_state

        left = forward
        for _ in range(8):
            left = left.rotate_left()
            if _can_progress(c, current, left):
                break

        right = forward
        for _ in range(8):
            right = right.rotate_right()
            if _can_progress(c, current, right):
                break

        left_dist = _chebyshev(current.add(left), target)
        right_dist = _chebyshev(current.add(right), target)
        if left_dist < right_dist:
            follow_state["obstacle_on_right"] = True
        elif right_dist < left_dist:
            follow_state["obstacle_on_right"] = False
        else:
            follow_state["obstacle_on_right"] = True

        if follow_state["obstacle_on_right"]:
            follow_state["obstacle_pos"] = current.add(left.rotate_right())
        else:
            follow_state["obstacle_pos"] = current.add(right.rotate_left())

    for can_rotate in (True, False):
        direction = current.direction_to(follow_state["obstacle_pos"])
        for _ in range(8):
            direction = (
                direction.rotate_left()
                if follow_state["obstacle_on_right"]
                else direction.rotate_right()
            )

            if _can_progress(c, current, direction):
                return direction, follow_state

            location = current.add(direction)
            if can_rotate and not on_map(c, location):
                follow_state["obstacle_on_right"] = not follow_state[
                    "obstacle_on_right"
                ]
                break

            if _is_hard_blocked(c, location):
                follow_state["obstacle_pos"] = location

    return None, follow_state
