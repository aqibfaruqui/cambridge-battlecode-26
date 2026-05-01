from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position

from utils.defense.combat import (
    area_is_safe as _area_is_safe,
    detect_attacked_tile as _detect_attacked_tile,
    find_enemy_pos as _find_enemy_pos,
    nearest_enemy_pos as _nearest_enemy_pos,
    step_toward as _step_toward,
)
from utils.axioniter_states.return_to_core import _planner_step_at, _reset_return_state
from utils.healing import try_heal_nearby_building
from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.axioniter import Axioniter


def _try_enter_defend(self: Axioniter, c: Controller) -> bool:
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


def _exit_defend(self: Axioniter) -> None:
    prev = self.defend_prev_state
    self.defend_prev_state = None
    self.defend_enemy_id = None
    self.defend_target_tile = None
    self.defend_gunner_pos = None
    self.defend_orig_conveyor_dir = None
    self.state = prev if prev is not None else type(self.state).SEEK


def _restart_return_from_splitter(self: Axioniter, splitter_pos: Position) -> None:
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


def _splitter_facing(self: Axioniter, c: Controller, tile: Position) -> Direction | None:
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


def _handle_post_build(self: Axioniter, c: Controller) -> None:
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


def _defend(self: Axioniter, c: Controller) -> None:
    try_heal_nearby_building(c, self.current_pos)

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
    
    if tile_bid is not None:
        if c.get_entity_type(tile_bid) == EntityType.CONVEYOR:
            d = c.get_direction(tile_bid)
            maybe_harvester = c.get_tile_building_id(c.get_position(tile_bid).add(d))
            if maybe_harvester is not None and c.get_entity_type(maybe_harvester) == EntityType.HARVESTER:
                if c.can_build_gunner(tile, tile.direction_to(enemy_pos if enemy_pos is not None else me)):
                    c.build_gunner(tile, tile.direction_to(enemy_pos if enemy_pos is not None else me))
                    self.defend_gunner_pos = tile
                return

    if tile_bid is not None and c.can_heal(tile):
        c.heal(tile)
        return

    if tile_bid is None:
        nearest = _nearest_enemy_pos(c)
        facing = tile.direction_to(nearest) if nearest is not None else tile.direction_to(me)
        if c.can_build_gunner(tile, facing):
            c.build_gunner(tile, facing)
            self.defend_gunner_pos = tile
