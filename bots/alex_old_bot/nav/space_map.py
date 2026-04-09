from enum import IntEnum

from cambc import Controller, Position, EntityType, Environment, ResourceType


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

_CARDINAL_DELTAS = ((0, 1), (0, -1), (1, 0), (-1, 0))

_ORE_ENVS_TO_AVOID = {
    ResourceType.TITANIUM: frozenset({Environment.ORE_AXIONITE}),
    ResourceType.RAW_AXIONITE: frozenset({Environment.ORE_TITANIUM}),
    ResourceType.REFINED_AXIONITE: frozenset(
        {Environment.ORE_AXIONITE, Environment.ORE_TITANIUM}
    ),
}


def build_space_map(
    c: Controller,
    *,
    allow_self: bool = False,
    avoid_ores: bool = False,
    avoid_ore_adjacency: ResourceType | None = None,
    avoid_core: bool = False,
    passable_buildings: frozenset[EntityType] = PASSABLE_BUILDINGS,
    restrict_to_our_buildings: bool = False,
    destroy: list[EntityType] = [EntityType.MARKER],
) -> list[list[GotoTileRepresentation]]:
    """Build a 9x9 passability grid centred on the bot for use by the pathfinder.

    Each cell is one of:
      CAN_MOVE — the bot can path through this tile.
      DESTROY  — passable, but the bot must destroy the building first.
      AVOID    — impassable (wall, enemy building, occupied tile, etc.).

    The grid starts from _SM_TEMPLATE (AVOID inside vision, CAN_MOVE outside)
    then iterates visible tiles to upgrade passable ones to CAN_MOVE/DESTROY.
    Tiles that remain unvisited (walls, tiles with another builder bot) stay AVOID.

    Args:
        allow_self:               Treat the bot's own tile as passable.
        avoid_ores:               Mark ore tiles (titanium / axionite) as AVOID.
        avoid_ore_adjacency:      When carrying this resource type, avoid tiles
                                  adjacent to conflicting ore (prevents wrong
                                  resource contamination).
        avoid_core:               Mark our own core as AVOID (e.g. for pathing
                                  around it rather than through it).
        passable_buildings:       Building types the bot can walk on.
        restrict_to_our_buildings: Only allow passable_buildings that we own.
        destroy:                  Own building types to mark DESTROY instead of
                                  AVOID (bot will tear them down to pass).
    """
    space_map = [row[:] for row in _SM_TEMPLATE]
    cx, cy = c.get_position().x, c.get_position().y
    my_team = c.get_team()
    my_id = c.get_id() if allow_self else None

    if avoid_ore_adjacency is not None:
        avoid_envs = _ORE_ENVS_TO_AVOID[avoid_ore_adjacency]
        map_w, map_h = c.get_map_width(), c.get_map_height()

    for tile in c.get_nearby_tiles():
        sx, sy = tile.x - cx + 4, tile.y - cy + 4

        env = c.get_tile_env(tile)

        if env == Environment.WALL:
            continue

        builder_bot_id = c.get_tile_builder_bot_id(tile)
        if builder_bot_id is not None and builder_bot_id != my_id:
            continue

        if avoid_ores and env in (
            Environment.ORE_TITANIUM,
            Environment.ORE_AXIONITE,
        ):
            continue

        building_id = c.get_tile_building_id(tile)
        if building_id is None:
            if avoid_ore_adjacency is not None:
                tx, ty = tile.x, tile.y
                blocked = False
                for ddx, ddy in _CARDINAL_DELTAS:
                    ax, ay = tx + ddx, ty + ddy
                    if 0 <= ax < map_w and 0 <= ay < map_h:
                        adj = Position(ax, ay)
                        if c.is_in_vision(adj) and c.get_tile_env(adj) in avoid_envs:
                            blocked = True
                            break
                if blocked:
                    continue
            space_map[sx][sy] = GotoTileRepresentation.CAN_MOVE
            continue

        owned = my_team == c.get_team(building_id)
        entity_type = c.get_entity_type(building_id)

        if entity_type in passable_buildings:
            space_map[sx][sy] = (
                GotoTileRepresentation.CAN_MOVE
                if not restrict_to_our_buildings or owned
                else GotoTileRepresentation.AVOID
            )
        elif entity_type == EntityType.CORE and owned and not avoid_core:
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
