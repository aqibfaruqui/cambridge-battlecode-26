from cambc import Controller, Environment, Position
from utils.pathfinding.movement import on_map


def is_ore_titanium(c: Controller, pos: Position) -> bool:
    if not on_map(c, pos):
        return False
    return c.get_tile_env(pos) == Environment.ORE_TITANIUM


def is_ore_axionite(c: Controller, pos: Position) -> bool:
    if not on_map(c, pos):
        return False
    return c.get_tile_env(pos) == Environment.ORE_AXIONITE


def is_ore(c: Controller, pos: Position) -> bool:
    return is_ore_titanium(c, pos) or is_ore_axionite(c, pos)
