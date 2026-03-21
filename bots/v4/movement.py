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
    if current_pos.x == core_pos.x and abs(current_pos.y - current_pos.y) <= 1:
        return True
    if current_pos.y == core_pos.y and abs(current_pos.x - current_pos.x) <= 1:
        return True
    return False
