import random
from cambc import Controller, Direction, Position

DIRECTIONS_4 = [
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
]

DIRECTIONS_8 = [
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
]

DIAGONALS = [
    Direction.NORTHEAST,
    Direction.NORTHWEST,
    Direction.SOUTHEAST,
    Direction.SOUTHWEST,
]


def on_map(c: Controller, pos: Position):
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def _manhattan(a: Position, b: Position):
    return abs(a.x - b.x) + abs(a.y - b.y)


def _chebyshev(a: Position, b: Position):
    return max(abs(a.x - b.x), abs(a.y - b.y))


def get_direction_4(current: Position, target: Position):
    best_dir = None
    best_dist = float("inf")

    for d in DIRECTIONS_4:
        new_pos = current.add(d)
        dist = _manhattan(new_pos, target)

        if dist < best_dist:
            best_dist = dist
            best_dir = d

    return best_dir


def get_direction_8(current: Position, target: Position):
    best_dir = None
    best_dist = float("inf")

    for d in DIRECTIONS_8:
        new_pos = current.add(d)
        dist = _manhattan(new_pos, target)

        if dist < best_dist:
            best_dist = dist
            best_dir = d

    return best_dir


def random_direction_4():
    return random.choice(DIRECTIONS_4)


def random_direction_8():
    return random.choice(DIRECTIONS_8)


def reached_core(current_pos: Position, core_pos: Position):
    return current_pos.distance_squared(core_pos) <= 1


def direction_from_centre(c: Controller, pos: Position):
    centre = Position(c.get_map_width() // 2, c.get_map_height() // 2)
    return centre.direction_to(pos)


def direction_to_centre(c: Controller, pos: Position):
    centre = Position(c.get_map_width() // 2, c.get_map_height() // 2)
    return pos.direction_to(centre)


# Both *_diagonal() functions are intended for 2x2 square scenarios
def is_diagonal(current: Position, target: Position):
    return False if current.direction_to(target) in DIRECTIONS_4 else True


def split_diagonal(current: Position, target: Position):
    match current.direction_to(target):
        case Direction.NORTHEAST:
            return (Direction.NORTH, Direction.EAST)
        case Direction.SOUTHEAST:
            return (Direction.SOUTH, Direction.EAST)
        case Direction.SOUTHWEST:
            return (Direction.SOUTH, Direction.WEST)
        case Direction.NORTHWEST:
            return (Direction.NORTH, Direction.WEST)
        case _:
            return (None, None)


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
