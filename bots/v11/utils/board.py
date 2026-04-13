from cambc import Controller, EntityType, Environment, Position
from utils.movement import DIRECTIONS_4, on_map

action_radius = {
    "bot": 2,
}


def is_wall(c: Controller, pos: Position) -> bool:
    return c.get_tile_env(pos) == Environment.WALL


def is_tile_conveyor(c: Controller, pos: Position) -> bool:
    id = c.get_tile_building_id(pos)
    if id is None:
        return False

    etype = c.get_entity_type(id)
    return etype == EntityType.CONVEYOR


def is_tile_foundry(c: Controller, pos: Position) -> bool:
    id = c.get_tile_building_id(pos)
    if id is None:
        return False

    etype = c.get_entity_type(id)
    return etype == EntityType.FOUNDRY


def is_tile_splitter(c: Controller, pos: Position) -> bool:
    id = c.get_tile_building_id(pos)
    if id is None:
        return False

    etype = c.get_entity_type(id)
    return etype == EntityType.SPLITTER


def replace_with_conveyor(c: Controller, pos: Position, core_pos: Position):
    if c.can_destroy(pos):
        c.destroy(pos)
        conveyor_dir = pos.direction_to(core_pos)
        if conveyor_dir not in DIRECTIONS_4:
            conveyor_dir = conveyor_dir.rotate_left()
        if c.can_build_conveyor(pos, conveyor_dir):
            c.build_conveyor(pos, conveyor_dir)


def is_ore_titanium(c: Controller, pos: Position) -> bool:
    if not on_map(c, pos):
        return False
    env = c.get_tile_env(pos)
    return env == Environment.ORE_TITANIUM


def is_ore_axionite(c: Controller, pos: Position) -> bool:
    if not on_map(c, pos):
        return False
    env = c.get_tile_env(pos)
    return env == Environment.ORE_AXIONITE


def is_ore(c: Controller, pos: Position) -> bool:
    return is_ore_titanium(c, pos) or is_ore_axionite(c, pos)


def _nearest_unclaimed(c: Controller, pos: Position, is_ore_type) -> Position:
    """Find closest visible ore tile (by is_ore_type) that isn't already harvested."""
    best_tile = None
    best_dist = float("inf")

    for tile in c.get_nearby_tiles():
        if not is_ore_type(c, tile):
            continue

        build_id = c.get_tile_building_id(tile)
        if build_id is not None:
            etype = c.get_entity_type(build_id)
            if etype == EntityType.HARVESTER:
                continue
            if etype != EntityType.ROAD and c.can_destroy(tile):
                return tile

        dist = pos.distance_squared(tile)
        if dist < best_dist:
            best_dist = dist
            best_tile = tile

    return best_tile


def nearby_titanium(c: Controller, pos: Position) -> Position:
    return _nearest_unclaimed(c, pos, is_ore_titanium)


def nearby_ore(c: Controller, pos: Position) -> Position:
    return _nearest_unclaimed(c, pos, is_ore)


def on_core_border(pos: Position, core_pos: Position):
    dx = abs(pos.x - core_pos.x)
    dy = abs(pos.y - core_pos.y)

    return max(dx, dy) == 2 and min(dx, dy) <= 1
