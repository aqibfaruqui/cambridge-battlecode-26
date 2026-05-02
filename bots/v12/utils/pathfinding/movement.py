import random
from cambc import Controller, Direction, EntityType, Environment, Position

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


def _chebyshev(a: Position, b: Position):
    return max(abs(a.x - b.x), abs(a.y - b.y))


def get_direction_4(current: Position, target: Position) -> Direction:
    best_dir = None
    best_dist = float("inf")

    for d in DIRECTIONS_4:
        new_pos = current.add(d)
        dist = _manhattan(new_pos, target)

        if dist < best_dist:
            best_dist = dist
            best_dir = d

    if best_dir is None:
        raise ValueError("get_direction_4 returned None, impossible")

    return best_dir


def random_direction_4():
    return random.choice(DIRECTIONS_4)


def random_direction_8():
    return random.choice(DIRECTIONS_8)


def advance_with_road(
    c: Controller,
    current_pos: Position,
    move_dir: Direction | None,
) -> None:
    """Clear a marker, pave the next empty tile, then move onto it."""
    if move_dir is None:
        return

    move_pos = current_pos.add(move_dir)
    build_id = c.get_tile_building_id(move_pos)
    if (
        build_id is not None
        and c.get_entity_type(build_id) == EntityType.MARKER
        and c.can_destroy(move_pos)
    ):
        c.destroy(move_pos)

    if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if c.can_move(move_dir):
        c.move(move_dir)


def reached_core(current_pos: Position, core_pos: Position):
    return (
        abs(current_pos.x - core_pos.x) <= 1
        and abs(current_pos.y - core_pos.y) <= 1
    )


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
