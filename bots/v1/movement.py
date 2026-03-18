import random
from cambc import Direction

DIRECTIONS = [
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
]

def _manhattan(a, b):
    return abs(a.x - b.x) + abs(a.y - b.y)

def get_direction(current, target):
    best_dir = None
    best_dist = float("inf")

    for d in DIRECTIONS:
        new_pos = current.add(d)
        dist = _manhattan(new_pos, target)

        if dist < best_dist:
            best_dist = dist
            best_dir = d

    return best_dir

def random_direction():
    return random.choice(DIRECTIONS)