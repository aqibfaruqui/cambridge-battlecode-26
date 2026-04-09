from cambc import Direction, Controller, Position

DIRS = [
    Direction.NORTH,
    Direction.NORTHEAST,
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
]

DIRS_OPPOSITE = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
    Direction.SOUTHEAST: Direction.NORTHWEST,
    Direction.SOUTHWEST: Direction.NORTHEAST,
    Direction.NORTHWEST: Direction.SOUTHEAST,
    Direction.NORTHEAST: Direction.SOUTHWEST,
}

DIRS_CARDINAL = [Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST]
DIRS_DIAGONAL = [
    Direction.SOUTHWEST,
    Direction.NORTHEAST,
    Direction.NORTHWEST,
    Direction.SOUTHEAST,
]


def is_valid(c: Controller, pos: Position) -> bool:
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def adjacent_to(p1: Position, p2: Position, *, can_be_on: bool = False) -> bool:
    return p1.distance_squared(p2) <= 2 and (can_be_on or p1 != p2)


def cardinally_adjacent_to(
    p1: Position, p2: Position, *, can_be_on: bool = False
) -> bool:
    return p1.distance_squared(p2) == 1 and (can_be_on or p1 != p2)


def adjacent_positions(c: Controller, pos: Position) -> list[Position]:
    return [pos.add(direction) for direction in DIRS if is_valid(c, pos.add(direction))]


def cardinally_adjacent_positions(c: Controller, pos: Position) -> list[Position]:
    return [
        pos.add(direction)
        for direction in DIRS_CARDINAL
        if is_valid(c, pos.add(direction))
    ]


def left_of(direction: Direction) -> Direction:
    match direction:
        case Direction.NORTH:
            return Direction.WEST
        case Direction.WEST:
            return Direction.SOUTH
        case Direction.SOUTH:
            return Direction.EAST
        case Direction.EAST:
            return Direction.NORTH
        case Direction.SOUTHEAST:
            return Direction.NORTHEAST
        case Direction.SOUTHWEST:
            return Direction.SOUTHEAST
        case Direction.NORTHWEST:
            return Direction.SOUTHWEST
        case Direction.NORTHEAST:
            return Direction.NORTHWEST


def right_of(direction: Direction) -> Direction:
    match direction:
        case Direction.NORTH:
            return Direction.EAST
        case Direction.EAST:
            return Direction.SOUTH
        case Direction.SOUTH:
            return Direction.WEST
        case Direction.WEST:
            return Direction.NORTH
        case Direction.SOUTHEAST:
            return Direction.SOUTHWEST
        case Direction.SOUTHWEST:
            return Direction.NORTHWEST
        case Direction.NORTHWEST:
            return Direction.NORTHEAST
        case Direction.NORTHEAST:
            return Direction.SOUTHEAST
