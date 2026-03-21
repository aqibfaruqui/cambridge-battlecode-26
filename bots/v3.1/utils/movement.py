import random
from cambc import Direction, Position, Controller

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


def on_map(c: Controller, pos: Position):
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def _manhattan(a: Position, b: Position):
    return abs(a.x - b.x) + abs(a.y - b.y)


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
