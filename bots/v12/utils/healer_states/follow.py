from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position

from utils.defense.combat import (
    ATTACKABLE_TYPES,
    VISION_RADIUS_SQ,
    detect_attacked_tile,
    find_enemy_pos,
    step_toward,
)

if TYPE_CHECKING:
    from builders.healer import Healer


def _pick_closest_enemy_builder(c: Controller) -> int | None:
    me = c.get_position()
    my_team = c.get_team()
    best_id: int | None = None
    best_d = VISION_RADIUS_SQ + 1
    for uid in c.get_nearby_units(VISION_RADIUS_SQ):
        if c.get_team(uid) == my_team:
            continue
        if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
            continue
        d = me.distance_squared(c.get_position(uid))
        if d < best_d:
            best_d = d
            best_id = uid
    return best_id


def _try_enter_follow(self: Healer, c: Controller) -> bool:
    """In PATROL, acquire a tracked enemy builder if one is in vision."""
    from builders.healer import HealState

    if self.follow_enemy_id is not None:
        return False
    eid = _pick_closest_enemy_builder(c)
    if eid is None:
        return False
    self.follow_enemy_id = eid
    # Seed HP snapshots so detect_attacked_tile has prev-HP data next turn.
    detect_attacked_tile(self, c)
    self.state = HealState.FOLLOW
    return True


def _detect_attack_by_tracked(self: Healer, c: Controller) -> Position | None:
    """Return the tile being drilled by the tracked enemy, or None.

    Still updates self.enemy_tile_hp for every enemy-occupied ally tile so
    a switch between turns doesn't drop HP history.
    """
    my_team = c.get_team()
    tracked = self.follow_enemy_id
    new_tracking: dict[tuple[int, int], int] = {}
    hit: Position | None = None
    for uid in c.get_nearby_units():
        if c.get_team(uid) == my_team:
            continue
        pos = c.get_position(uid)
        if not c.is_in_vision(pos):
            continue
        bid = c.get_tile_building_id(pos)
        if bid is None:
            continue
        if c.get_team(bid) != my_team:
            continue
        if c.get_entity_type(bid) not in ATTACKABLE_TYPES:
            continue
        hp = c.get_hp(bid)
        key = (pos.x, pos.y)
        prev = self.enemy_tile_hp.get(key)
        new_tracking[key] = hp
        if hit is None and uid == tracked and prev is not None and hp < prev:
            hit = pos
    self.enemy_tile_hp = new_tracking
    return hit


def _follow(self: Healer, c: Controller) -> None:
    from builders.healer import HealState
    from utils.healer_states.defend import _try_enter_defend_healer

    enemy_id = self.follow_enemy_id
    if enemy_id is None:
        self.state = HealState.PATROL
        return

    enemy_pos = find_enemy_pos(c, enemy_id)
    if enemy_pos is None:
        c.self_destruct()
        return

    tile = _detect_attack_by_tracked(self, c)
    if tile is not None and _try_enter_defend_healer(self, c, tile):
        return

    if c.get_move_cooldown() > 0:
        return

    me = c.get_position()
    # Close to Chebyshev <= 2 so we can react fast but don't overlap the enemy.
    if me.distance_squared(enemy_pos) <= 2:
        return
    step_toward(c, me, enemy_pos)
