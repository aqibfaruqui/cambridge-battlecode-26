from cambc import Controller, EntityType, Position

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
    
def try_heal_nearby_conveyor(c: Controller, pos: Position) -> bool:
    """Heal the most-damaged allied conveyor within action radius (3x3). Returns True if healed."""
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
            if c.get_entity_type(bid) != EntityType.CONVEYOR:
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
