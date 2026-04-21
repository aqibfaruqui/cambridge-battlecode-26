from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position

from utils.defense.combat import (
    area_is_safe,
    find_enemy_pos,
    nearest_enemy_pos,
    step_toward,
)
from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.healer import Healer


def _splitter_facing_healer(self: Healer, tile: Position) -> Direction | None:
    if self.defend_orig_conveyor_dir is not None:
        return self.defend_orig_conveyor_dir
    fallback = tile.direction_to(self.core_pos)
    if fallback in DIRECTIONS_4:
        return fallback
    for d in DIRECTIONS_4:
        return d
    return None


def _exit_or_self_destruct(self: Healer, c: Controller) -> None:
    """After the combo: self-destruct if the tracked enemy is gone, else resume FOLLOW."""
    from builders.healer import HealState

    tracked = self.follow_enemy_id
    self.defend_enemy_id = None
    self.defend_target_tile = None
    self.defend_gunner_pos = None
    self.defend_orig_conveyor_dir = None

    if tracked is None or find_enemy_pos(c, tracked) is None:
        c.self_destruct()
        return
    self.state = HealState.FOLLOW


def _try_enter_defend_healer(self: Healer, c: Controller, tile: Position) -> bool:
    """Called from FOLLOW once the tracked enemy is drilling `tile`."""
    from builders.healer import HealState

    if self.ti < c.get_gunner_cost()[0]:
        return False

    tile_bid = c.get_tile_building_id(tile)
    if tile_bid is not None and c.get_entity_type(tile_bid) == EntityType.CONVEYOR:
        self.defend_orig_conveyor_dir = c.get_direction(tile_bid)
    else:
        self.defend_orig_conveyor_dir = None

    self.defend_enemy_id = self.follow_enemy_id
    self.defend_target_tile = tile
    self.defend_gunner_pos = None
    self.state = HealState.DEFEND
    return True


def _handle_post_build_healer(self: Healer, c: Controller) -> None:
    """Gunner has been placed — wait for safety, then destroy it and drop a splitter."""
    gunner_pos = self.defend_gunner_pos
    if gunner_pos is None:
        return

    my_team = c.get_team()
    tile_bid = c.get_tile_building_id(gunner_pos)

    if tile_bid is None:
        # Gunner already destroyed by enemies, or we cleared it last turn.
        if not area_is_safe(c):
            return
        facing = _splitter_facing_healer(self, gunner_pos)
        if facing is None:
            _exit_or_self_destruct(self, c)
            return
        if self.ti < c.get_splitter_cost()[0]:
            return
        if c.can_build_splitter(gunner_pos, facing):
            c.build_splitter(gunner_pos, facing)
            _exit_or_self_destruct(self, c)
        return

    if c.get_team(tile_bid) != my_team or c.get_entity_type(tile_bid) != EntityType.GUNNER:
        _exit_or_self_destruct(self, c)
        return

    if not area_is_safe(c):
        return

    if c.can_destroy(gunner_pos):
        c.destroy(gunner_pos)


def _defend_healer(self: Healer, c: Controller) -> None:
    if self.defend_gunner_pos is not None:
        _handle_post_build_healer(self, c)
        return

    tile = self.defend_target_tile
    enemy_id = self.defend_enemy_id
    if tile is None or enemy_id is None:
        _exit_or_self_destruct(self, c)
        return

    me = c.get_position()
    my_team = c.get_team()

    tile_bid = c.get_tile_building_id(tile)
    if tile_bid is not None and c.get_team(tile_bid) != my_team:
        _exit_or_self_destruct(self, c)
        return

    enemy_pos = find_enemy_pos(c, enemy_id)
    enemy_on_tile = enemy_pos is not None and enemy_pos == tile
    dist_sq = me.distance_squared(tile)

    if enemy_on_tile:
        if me == tile:
            for d in DIRECTIONS_4:
                if c.can_move(d):
                    c.move(d)
                    return
            return
        if dist_sq <= 2:
            facing = tile.direction_to(enemy_pos if enemy_pos is not None else me)
            if c.can_build_gunner(tile, facing):
                c.build_gunner(tile, facing)
                self.defend_gunner_pos = tile
                return
            if c.can_build_road(tile):
                c.build_road(tile)
            return
        step_toward(c, me, tile)
        return

    # Enemy moved off (or died / left vision). Close in and place a gunner.
    if dist_sq > 2:
        step_toward(c, me, tile)
        return

    if tile_bid is not None and c.can_destroy(tile):
        c.destroy(tile)
        tile_bid = c.get_tile_building_id(tile)

    if tile_bid is None:
        nearest = nearest_enemy_pos(c)
        facing = tile.direction_to(nearest) if nearest is not None else tile.direction_to(me)
        if c.can_build_gunner(tile, facing):
            c.build_gunner(tile, facing)
            self.defend_gunner_pos = tile
