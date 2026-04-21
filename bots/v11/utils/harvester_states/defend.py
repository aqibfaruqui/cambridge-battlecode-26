from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position

from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.harvester import Harvester


_VISION_RADIUS_SQ = 20

# Only infrastructure types a builder bot can actually chew through on its own tile.
_ATTACKABLE_TYPES = {EntityType.CONVEYOR, EntityType.BRIDGE}


def _nearest_enemy_pos(c: Controller) -> Position | None:
    my_team = c.get_team()
    me = c.get_position()
    best_pos: Position | None = None
    best_d = _VISION_RADIUS_SQ + 1
    for uid in c.get_nearby_units(_VISION_RADIUS_SQ):
        if c.get_team(uid) == my_team:
            continue
        pos = c.get_position(uid)
        d = me.distance_squared(pos)
        if d < best_d:
            best_d = d
            best_pos = pos
    return best_pos


def _detect_attacked_tile(self: Harvester, c: Controller) -> tuple[int, Position] | None:
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
        if c.get_entity_type(bid) not in _ATTACKABLE_TYPES:
            continue
        hp = c.get_hp(bid)
        key = (pos.x, pos.y)
        prev = self.enemy_tile_hp.get(key)
        new_tracking[key] = hp
        if attack is None and prev is not None and hp < prev:
            attack = (uid, pos)
    self.enemy_tile_hp = new_tracking
    return attack


def _try_enter_defend(self: Harvester, c: Controller) -> bool:
    attack = _detect_attacked_tile(self, c)
    if attack is None:
        return False
    if self.ti < c.get_gunner_cost()[0]:
        return False

    enemy_id, tile = attack
    self.defend_prev_state = self.state
    self.defend_enemy_id = enemy_id
    self.defend_target_tile = tile
    self.state = type(self.state).DEFEND
    return True


def _exit_defend(self: Harvester) -> None:
    prev = self.defend_prev_state
    self.defend_prev_state = None
    self.defend_enemy_id = None
    self.defend_target_tile = None
    self.state = prev if prev is not None else type(self.state).SEEK


def _find_enemy_pos(c: Controller, enemy_id: int) -> Position | None:
    for uid in c.get_nearby_units(_VISION_RADIUS_SQ):
        if uid == enemy_id:
            return c.get_position(uid)
    return None


def _step_toward(c: Controller, me: Position, target: Position) -> None:
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


def _defend(self: Harvester, c: Controller) -> None:
    tile = self.defend_target_tile
    enemy_id = self.defend_enemy_id
    if tile is None or enemy_id is None:
        _exit_defend(self)
        return

    me = self.current_pos
    my_team = c.get_team()

    # If something enemy-owned occupies the tile now, we've lost this one.
    tile_bid = c.get_tile_building_id(tile)
    if tile_bid is not None and c.get_team(tile_bid) != my_team:
        _exit_defend(self)
        return

    enemy_pos = _find_enemy_pos(c, enemy_id)
    enemy_on_tile = enemy_pos is not None and enemy_pos == tile
    dist_sq = me.distance_squared(tile)

    if enemy_on_tile:
        # Pathfind to a tile adjacent to the attacked tile and wait.
        if me == tile:
            for d in DIRECTIONS_4:
                if c.can_move(d):
                    c.move(d)
                    return
            return
        if dist_sq <= 2:
            if c.can_build_gunner(tile, tile.direction_to(enemy_pos if enemy_pos is not None else me)):
                c.build_gunner(tile, tile.direction_to(enemy_pos if enemy_pos is not None else me))
                _exit_defend(self)
                return
            if c.can_build_road(tile):
                c.build_road(tile)
            return
        _step_toward(c, me, tile)
        return

    # Enemy moved off (or died / left vision). Close in and place a gunner.
    if dist_sq > 2:
        _step_toward(c, me, tile)
        return

    if tile_bid is not None and c.can_destroy(tile):
        c.destroy(tile)
        tile_bid = c.get_tile_building_id(tile)

    if tile_bid is None:
        nearest = _nearest_enemy_pos(c)
        facing = tile.direction_to(nearest) if nearest is not None else tile.direction_to(me)
        if c.can_build_gunner(tile, facing):
            c.build_gunner(tile, facing)
            _exit_defend(self)
