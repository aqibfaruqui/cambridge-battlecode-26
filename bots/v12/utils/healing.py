from cambc import Controller, EntityType, Position


_HEALABLE_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.CORE,
    EntityType.HARVESTER,
    EntityType.SPLITTER,
    EntityType.FOUNDRY,
})


def try_heal_nearby_bot(c: Controller, pos: Position) -> bool:
    """Heal self if damaged, otherwise heal the nearest damaged friendly builder bot
    within action radius. Returns True if a heal was performed."""
    if c.get_action_cooldown() > 0:
        return False
    my_id = c.get_id()
    my_team = c.get_team()
    if c.get_hp(my_id) < c.get_max_hp(my_id) and c.can_heal(pos):
        c.heal(pos)
        return True
    w, h = c.get_map_width(), c.get_map_height()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            x, y = pos.x + dx, pos.y + dy
            if not (0 <= x < w and 0 <= y < h):
                continue
            p = Position(x, y)
            if not c.is_in_vision(p):
                continue
            bot_id = c.get_tile_builder_bot_id(p)
            if bot_id is None:
                continue
            if c.get_team(bot_id) != my_team:
                continue
            if c.get_hp(bot_id) >= c.get_max_hp(bot_id):
                continue
            if not c.can_heal(p):
                continue
            c.heal(p)
            return True
    return False


def _try_heal_nearby_building_filtered(
    c: Controller, pos: Position, allowed_types: frozenset
) -> bool:
    """Heal the most-damaged allied building of `allowed_types` within action radius (3x3)."""
    if c.get_action_cooldown() > 0:
        return False
    my_team = c.get_team()
    w, h = c.get_map_width(), c.get_map_height()
    best: Position | None = None
    best_ratio = float("inf")
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            x, y = pos.x + dx, pos.y + dy
            if not (0 <= x < w and 0 <= y < h):
                continue
            p = Position(x, y)
            if not c.is_in_vision(p):
                continue
            bid = c.get_tile_building_id(p)
            if bid is None:
                continue
            if c.get_team(bid) != my_team:
                continue
            if c.get_entity_type(bid) not in allowed_types:
                continue
            max_hp = c.get_max_hp(bid)
            hp = c.get_hp(bid)
            if hp >= max_hp:
                continue
            if not c.can_heal(p):
                continue
            ratio = hp / max_hp
            if ratio < best_ratio:
                best_ratio = ratio
                best = p
    if best is None:
        return False
    c.heal(best)
    return True


def try_heal_nearby_building(c: Controller, pos: Position) -> bool:
    """Heal the most-damaged allied building within action radius (3x3). Returns True if healed."""
    return _try_heal_nearby_building_filtered(c, pos, _HEALABLE_TYPES)


_CONVEYOR_ONLY = frozenset({EntityType.CONVEYOR})


def try_heal_nearby_conveyor(c: Controller, pos: Position) -> bool:
    """Heal the most-damaged allied conveyor within action radius (3x3). Returns True if healed."""
    return _try_heal_nearby_building_filtered(c, pos, _CONVEYOR_ONLY)


def _find_damaged_conveyor(c: Controller) -> Position | None:
    """Scan all buildings in vision for the most-damaged allied conveyor or bridge."""
    my_team = c.get_team()
    best_pos: Position | None = None
    best_ratio = float("inf")
    for bid in c.get_nearby_buildings():
        if c.get_team(bid) != my_team:
            continue
        if c.get_entity_type(bid) not in (EntityType.CONVEYOR, EntityType.BRIDGE):
            continue
        max_hp = c.get_max_hp(bid)
        hp = c.get_hp(bid)
        if hp >= max_hp:
            continue
        ratio = hp / max_hp
        if ratio < best_ratio:
            best_ratio = ratio
            best_pos = c.get_position(bid)
    return best_pos
