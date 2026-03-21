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

def bug_nav(c: Controller, current: Position, target: Position, follow_dir: Direction = None):
    # current_dir is the direction the bot is currently following along wall
    # Returns the move direction and the direction the bot should be following along wall
    preferred_move = get_direction_4(current, target) # only move in cardinal directions as conveyors need to be placed
    
    if follow_dir is None:
        if c.can_move(preferred_move):
            return preferred_move, follow_dir
        
        # Hit a wall, pick side closer to target

        left_side = preferred_move.rotate_left().rotate_left() # 90 degrees left
        right_side = preferred_move.rotate_right().rotate_right() # 90 degrees right

        if _manhattan(current.add(left_side), target) < _manhattan(current.add(right_side), target):
            follow_dir = left_side
        else:
            follow_dir = right_side
    
    # Exit wall-hugging as soon as direct path clears (keep follow_dir to prevent oscillation)
    if c.can_move(preferred_move):
        return preferred_move, follow_dir
    
    for d in (
        follow_dir,
        follow_dir.rotate_left().rotate_left(),
        follow_dir.rotate_right().rotate_right(),
        follow_dir.rotate_right().rotate_right().rotate_right().rotate_right(),
    ):
        if c.can_move(d):
            return d, d
    
    return None, follow_dir # completely surrounded