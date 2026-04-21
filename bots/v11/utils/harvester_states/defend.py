from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position

from utils.harvester_states.return_to_core import _planner_step_at, _reset_return_state
from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.harvester import Harvester


_VISION_RADIUS_SQ = 20

# Only infrastructure types a builder bot can actually chew through on its own tile.
_ATTACKABLE_TYPES = {EntityType.CONVEYOR, EntityType.BRIDGE}

# LAUNCHER excluded: it throws builders, doesn't shoot on its own.
_UNSAFE_ENEMY_TYPES = frozenset({
    EntityType.BUILDER_BOT,
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
})


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


def _area_is_safe(c: Controller) -> bool:
    my_team = c.get_team()
    for uid in c.get_nearby_units(_VISION_RADIUS_SQ):
        if c.get_team(uid) == my_team:
            continue
        if c.get_entity_type(uid) in _UNSAFE_ENEMY_TYPES:
            return False
    return True


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
    # Capture original conveyor direction (if any) to orient the replacement splitter later.
    tile_bid = c.get_tile_building_id(tile)
    if tile_bid is not None and c.get_entity_type(tile_bid) == EntityType.CONVEYOR:
        self.defend_orig_conveyor_dir = c.get_direction(tile_bid)
    else:
        self.defend_orig_conveyor_dir = None

    self.defend_prev_state = self.state
    self.defend_enemy_id = enemy_id
    self.defend_target_tile = tile
    self.defend_gunner_pos = None
    self.state = type(self.state).DEFEND
    return True


def _exit_defend(self: Harvester) -> None:
    prev = self.defend_prev_state
    self.defend_prev_state = None
    self.defend_enemy_id = None
    self.defend_target_tile = None
    self.defend_gunner_pos = None
    self.defend_orig_conveyor_dir = None
    self.state = prev if prev is not None else type(self.state).SEEK


def _restart_return_from_splitter(self: Harvester, splitter_pos: Position) -> None:
    """Hand off to RETURN, treating the freshly-placed splitter as the harvester source."""
    self.harvester_pos = splitter_pos
    self.just_placed = True
    _reset_return_state(self)
    self.defend_prev_state = None
    self.defend_enemy_id = None
    self.defend_target_tile = None
    self.defend_gunner_pos = None
    self.defend_orig_conveyor_dir = None
    self.state = type(self.state).RETURN


def _splitter_facing(self: Harvester, c: Controller, tile: Position) -> Direction | None:
    facing = self.defend_orig_conveyor_dir
    if facing is not None:
        return facing
    facing = _planner_step_at(self, c, tile)
    if facing is not None and facing in DIRECTIONS_4:
        return facing
    fallback = tile.direction_to(self.core_pos)
    if fallback in DIRECTIONS_4:
        return fallback
    return None


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


def _handle_post_build(self: Harvester, c: Controller) -> None:
    """Gunner has been placed — wait for safety, then destroy it and drop a splitter."""
    gunner_pos = self.defend_gunner_pos
    if gunner_pos is None:
        return

    my_team = c.get_team()
    tile_bid = c.get_tile_building_id(gunner_pos)

    # Gunner gone (destroyed by enemies, or tile was taken over): bail out.
    if tile_bid is None:
        # Tile is empty — proceed straight to splitter placement if area is safe.
        if not _area_is_safe(c):
            return
        facing = _splitter_facing(self, c, gunner_pos)
        if facing is None:
            _exit_defend(self)
            return
        if self.ti < c.get_splitter_cost()[0]:
            return
        if c.can_build_splitter(gunner_pos, facing):
            c.build_splitter(gunner_pos, facing)
            _restart_return_from_splitter(self, gunner_pos)
        return

    if c.get_team(tile_bid) != my_team or c.get_entity_type(tile_bid) != EntityType.GUNNER:
        # Our gunner was replaced by something else — give up on the swap.
        _exit_defend(self)
        return

    if not _area_is_safe(c):
        return

    if c.can_destroy(gunner_pos):
        c.destroy(gunner_pos)


def _defend(self: Harvester, c: Controller) -> None:
    # Post-build phase: gunner is placed, now wait for safety and swap to a splitter.
    if self.defend_gunner_pos is not None:
        _handle_post_build(self, c)
        return

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
                self.defend_gunner_pos = tile
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
            self.defend_gunner_pos = tile
