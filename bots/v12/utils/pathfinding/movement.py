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


_BUILDER_WALKABLE_BUILDINGS = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
        EntityType.ROAD,
    }
)
_ROAD_REPLACEABLE_BUILDINGS = frozenset({EntityType.ROAD, EntityType.MARKER})
_ROAD_PLACEABLE_ENV = frozenset(
    {Environment.EMPTY, Environment.ORE_TITANIUM, Environment.ORE_AXIONITE}
)


def is_builder_dynamic_blocker(c: Controller, pos: Position, my_id: int | None = None) -> bool:
    if my_id is not None:
        bot_id = c.get_tile_builder_bot_id(pos)
        if bot_id is not None and bot_id != my_id:
            return True

    building_id = c.get_tile_building_id(pos)
    if building_id is None:
        return c.get_tile_env(pos) not in _ROAD_PLACEABLE_ENV

    entity_type = c.get_entity_type(building_id)
    if entity_type in _BUILDER_WALKABLE_BUILDINGS:
        return False
    if entity_type == EntityType.CORE and c.get_team(building_id) == c.get_team():
        return False
    if entity_type in _ROAD_REPLACEABLE_BUILDINGS:
        return False
    return True


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
    """Clear a marker, pave the next tile when legal, then move onto it."""
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

    if c.can_build_road(move_pos):
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
