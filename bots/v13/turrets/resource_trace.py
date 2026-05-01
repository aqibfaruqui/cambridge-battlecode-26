from cambc import Controller, Direction, EntityType, Position

_RELAY_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
})

_FRIENDLY_TURRET_TYPES = frozenset({EntityType.GUNNER, EntityType.SENTINEL})


def feeds_friendly_turret(c: Controller, start_pos: Position, my_team) -> bool:
    """Trace resource flow forward from start_pos through relay tiles.

    Returns True if any path reaches a friendly gunner/sentinel OR leaves
    vision / the map — unknown destinations are treated as unsafe so we
    don't accidentally shoot out our own supply chain.

    Returns False only when every branch terminates at a known dead end
    (empty tile or non-relay/non-turret building).
    """
    visited: set[tuple[int, int]] = set()
    stack: list[Position] = [start_pos]
    W, H = c.get_map_width(), c.get_map_height()

    while stack:
        pos = stack.pop()
        key = (pos.x, pos.y)
        if key in visited:
            continue
        visited.add(key)

        if not (0 <= pos.x < W and 0 <= pos.y < H):
            return True
        if not c.is_in_vision(pos):
            return True

        bld_id = c.get_tile_building_id(pos)
        if bld_id is None:
            continue

        etype = c.get_entity_type(bld_id)
        if c.get_team(bld_id) == my_team and etype in _FRIENDLY_TURRET_TYPES:
            return True

        if etype not in _RELAY_TYPES:
            continue

        if etype == EntityType.BRIDGE:
            stack.append(c.get_bridge_target(bld_id))
            continue

        facing = c.get_direction(bld_id)
        if facing == Direction.CENTRE:
            continue

        if etype == EntityType.SPLITTER:
            stack.append(pos.add(facing))
            stack.append(pos.add(facing.rotate_left().rotate_left()))
            stack.append(pos.add(facing.rotate_right().rotate_right()))
        else:
            stack.append(pos.add(facing))

    return False
