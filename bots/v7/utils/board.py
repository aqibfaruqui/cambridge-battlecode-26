from cambc import Controller, EntityType, Environment, Position
from utils.movement import on_map

action_radius = {
    "bot": 2,
}


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


def nearest_ore_tile(c: Controller, pos: Position):
    for tile in c.get_nearby_tiles():
        if not is_ore_titanium(c, tile):
            continue

        build_id = c.get_tile_building_id(tile)
        if build_id is None:
            return tile

        etype = c.get_entity_type(build_id)
        if etype == EntityType.ROAD and c.can_destroy(tile):
            return tile

    return None


def on_core_border(pos: Position, core_pos: Position):
    dx = abs(pos.x - core_pos.x)
    dy = abs(pos.y - core_pos.y)

    return max(dx, dy) == 2 and min(dx, dy) <= 1
