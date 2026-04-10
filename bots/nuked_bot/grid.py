from cambc import Direction, Controller, Position
from typing import NamedTuple

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


def horizontally_symmetric(c: Controller, point: Position) -> Position:
    """Returns the point reflecred in horizontal symmetry"""
    return Position(c.get_map_width() - 1 - point.x, point.y)


def rotationally_symmetric(c: Controller, point: Position) -> Position:
    """Returns the point reflected in rotational symmetry"""
    return Position(c.get_map_width() - 1 - point.x, c.get_map_height() - 1 - point.y)


def vertically_symmetric(c: Controller, point: Position) -> Position:
    """Returns the point reflected in vertical symmetry"""
    return Position(point.x, c.get_map_height() - 1 - point.y)


def in_bounds(c: Controller, pos: Position) -> bool:
    """Checks if a position is in map dimensions"""
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def adjacent_to(p1: Position, p2: Position, *, can_be_on: bool = False) -> bool:
    """Checks if p1 is adjacent to p2, optionally can_be_on is false"""
    return p1.distance_squared(p2) <= 2 and (can_be_on or p1 != p2)


def is_cardinally_adjacent_to(
    p1: Position, p2: Position, *, can_be_on: bool = False
) -> bool:
    """Checks if p1 is cardinally adjacent to p2, optionally can_be_on is false"""
    return p1.distance_squared(p2) == 1 and (can_be_on or p1 != p2)


def adjacent_positions(c: Controller, pos: Position) -> list[Position]:
    """Adjacent positions not including input `pos`, guaranteed in bounds"""
    return [
        pos.add(direction) for direction in DIRS if in_bounds(c, pos.add(direction))
    ]


def cardinally_adjacent_positions(c: Controller, pos: Position) -> list[Position]:
    """Cardinally adjacent positions not including input `pos`, guaranteed in bounds"""
    return [
        pos.add(direction)
        for direction in DIRS_CARDINAL
        if in_bounds(c, pos.add(direction))
    ]


def left_of(direction: Direction) -> Direction:
    """Returns the direction 90 degrees anticlockwise of any direction"""
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
    """Returns the direction 90 degrees clockwise of any direction"""
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
