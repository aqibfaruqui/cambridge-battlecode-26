"""Shared combat helpers used by harvester and healer DEFEND logic."""
from __future__ import annotations
from typing import Protocol

from cambc import Controller, EntityType, Position

from utils.pathfinding.movement import DIRECTIONS_4


VISION_RADIUS_SQ = 20

# Only infrastructure types a builder bot can actually chew through on its own tile.
ATTACKABLE_TYPES = {EntityType.CONVEYOR, EntityType.BRIDGE}

# LAUNCHER excluded: it throws builders, doesn't shoot on its own.
UNSAFE_ENEMY_TYPES = frozenset({
    EntityType.BUILDER_BOT,
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
})


class HasEnemyTileHp(Protocol):
    enemy_tile_hp: dict[tuple[int, int], int]


def nearest_enemy_pos(c: Controller) -> Position | None:
    my_team = c.get_team()
    me = c.get_position()
    best_pos: Position | None = None
    best_d = VISION_RADIUS_SQ + 1
    for uid in c.get_nearby_units(VISION_RADIUS_SQ):
        if c.get_team(uid) == my_team:
            continue
        pos = c.get_position(uid)
        d = me.distance_squared(pos)
        if d < best_d:
            best_d = d
            best_pos = pos
    return best_pos


def area_is_safe(c: Controller) -> bool:
    my_team = c.get_team()
    for uid in c.get_nearby_units(VISION_RADIUS_SQ):
        if c.get_team(uid) == my_team:
            continue
        if c.get_entity_type(uid) in UNSAFE_ENEMY_TYPES:
            return False
    return True


def find_enemy_pos(c: Controller, enemy_id: int) -> Position | None:
    for uid in c.get_nearby_units(VISION_RADIUS_SQ):
        if uid == enemy_id:
            return c.get_position(uid)
    return None


def step_toward(c: Controller, me: Position, target: Position) -> None:
    preferred = me.direction_to(target)
    if c.can_move(preferred):
        c.move(preferred)
        return
    cur_dist = me.distance_squared(target)
    best_d = None
    best_dist = cur_dist
    for d in DIRECTIONS_4:
        if d == preferred or not c.can_move(d):
            continue
        nd = me.add(d).distance_squared(target)
        if nd < best_dist:
            best_dist = nd
            best_d = d
    if best_d is not None:
        c.move(best_d)


def detect_attacked_tile(self: HasEnemyTileHp, c: Controller) -> tuple[int, Position] | None:
    """Track HP of ally conveyor/bridge tiles currently occupied by enemies."""
    my_team = c.get_team()
    new_tracking: dict[tuple[int, int], int] = {}
    attack: tuple[int, Position] | None = None
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
        if attack is None and prev is not None and hp < prev:
            attack = (uid, pos)
    self.enemy_tile_hp = new_tracking
    return attack
