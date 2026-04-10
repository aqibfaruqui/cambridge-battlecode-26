from enum import IntEnum

from cambc import Controller, Position, EntityType, Environment


class GotoTileRepresentation(IntEnum):
    CAN_MOVE = 0
    DESTROY = 1
    AVOID = 2


# Precomputed 9x9 grid centred on the bot (index 4,4).
# Tiles inside vision (dist² ≤ 20) default to AVOID so the pathfinder won't
# route through them unless build_space_map explicitly upgrades them.
# Tiles outside vision default to CAN_MOVE (optimistic).
# Shallow-copy rows via [row[:] for row in _SM_TEMPLATE] to get a fresh map.
_SM_TEMPLATE: list[list[GotoTileRepresentation]] = [
    [GotoTileRepresentation.AVOID] * 9 for _ in range(9)
]
for _dx in range(-4, 5):
    for _dy in range(-4, 5):
        if _dx * _dx + _dy * _dy > 20:
            _SM_TEMPLATE[_dx + 4][_dy + 4] = GotoTileRepresentation.CAN_MOVE

PASSABLE_BUILDINGS = frozenset(
    {
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.BRIDGE,
        EntityType.SPLITTER,
    }
)


def build_space_map(
    c: Controller,
    *,
    allow_self: bool = False,
    passable_buildings: frozenset[EntityType] = PASSABLE_BUILDINGS,
    destroy: list[EntityType] = [],
) -> list[list[GotoTileRepresentation]]:
    """Build a 9x9 passability grid centred on the bot for use by the pathfinder.

    Each cell is one of:
      CAN_MOVE — the bot can path through this tile.
      DESTROY  — passable, but the bot must destroy the building first.
      AVOID    — impassable (wall, enemy building, occupied tile, etc.).
    """
    space_map = [row[:] for row in _SM_TEMPLATE]
    cx, cy = c.get_position().x, c.get_position().y
    my_team = c.get_team()
    my_id = c.get_id() if allow_self else None

    for tile in c.get_nearby_tiles():
        sx, sy = tile.x - cx + 4, tile.y - cy + 4

        env = c.get_tile_env(tile)

        if env == Environment.WALL:
            continue

        builder_bot_id = c.get_tile_builder_bot_id(tile)
        if builder_bot_id is not None and builder_bot_id != my_id:
            continue

        building_id = c.get_tile_building_id(tile)
        if building_id is None:
            space_map[sx][sy] = GotoTileRepresentation.CAN_MOVE
            continue

        owned = my_team == c.get_team(building_id)
        entity_type = c.get_entity_type(building_id)

        if entity_type in passable_buildings:
            space_map[sx][sy] = GotoTileRepresentation.CAN_MOVE
        elif entity_type == EntityType.CORE and owned:
            space_map[sx][sy] = GotoTileRepresentation.CAN_MOVE
        elif owned and entity_type in destroy:
            space_map[sx][sy] = GotoTileRepresentation.DESTROY

    return space_map


def passable(tile: GotoTileRepresentation) -> bool:
    """True if the tile is CAN_MOVE or DESTROY (anything the bot can traverse)."""
    return tile != GotoTileRepresentation.AVOID


def to_sm(centre: Position, pos: Position) -> tuple[int, int]:
    """Convert a world Position to a space-map (sx, sy) index."""
    return (pos.x - centre.x + 4, pos.y - centre.y + 4)


def sm_in_bounds(sm: tuple[int, int]) -> bool:
    """True if the index is within the 9x9 space-map grid."""
    return 0 <= sm[0] < 9 and 0 <= sm[1] < 9


def passable_at(
    sm: tuple[int, int], space_map: list[list[GotoTileRepresentation]]
) -> bool:
    """True if the index is in bounds AND the tile is passable."""
    return sm_in_bounds(sm) and passable(space_map[sm[0]][sm[1]])


def dist_sq(ax: int, ay: int, bx: int, by: int) -> int:
    """Squared Euclidean distance between two points."""
    return (ax - bx) ** 2 + (ay - by) ** 2
