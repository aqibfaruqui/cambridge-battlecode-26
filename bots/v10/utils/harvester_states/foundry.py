from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller

from utils.board import (
    action_radius,
    is_tile_conveyor,
    is_tile_foundry,
    is_tile_splitter,
    on_core_border,
    replace_with_conveyor,
)
from utils.movement import DIRECTIONS_4, get_direction_4

if TYPE_CHECKING:
    from builders.harvester_revamped import Harvester


def _placing_foundry(self: Harvester, c: Controller) -> None:
    pos = self.current_pos

    # Foundry placed: Wait for axionite then destroy foundry
    if self.foundry_curr_placed:
        rounds_waiting = c.get_current_round() - self.foundry_placed_round
        if self.ax <= 0 and rounds_waiting < 40:
            return
        cost = c.get_conveyor_cost()[0]
        for tile in c.get_nearby_tiles(action_radius["bot"]):
            if is_tile_splitter(c, tile) and self.ti >= cost:
                replace_with_conveyor(c, tile, self.core_pos)
                self.splitter_for_foundry = False
                if self.foundry_prev_placed:
                    self.state = type(self.state).SEEK
                return
            elif is_tile_foundry(c, tile) and self.ti >= cost:
                replace_with_conveyor(c, tile, self.core_pos)
                self.foundry_prev_placed = True
                if not self.splitter_for_foundry:
                    self.state = type(self.state).SEEK
                return
        return

    # Positioning: get onto a conveyor
    if not is_tile_conveyor(c, pos):
        for d in DIRECTIONS_4:
            neighbor = pos.add(d)
            if is_tile_conveyor(c, neighbor) and c.can_move(d):
                c.move(d)
                return
        for tile in c.get_nearby_tiles(action_radius["bot"]):
            if is_tile_conveyor(c, tile):
                step_dir = get_direction_4(pos, tile)
                if c.can_move(step_dir):
                    c.move(step_dir)
                return
        return

    move_dir = c.get_direction(c.get_tile_building_id(pos))
    move_pos = pos.add(move_dir)

    # Too close to core: back up
    if max(abs(move_pos.x - self.core_pos.x), abs(move_pos.y - self.core_pos.y)) < 2:
        back_dir = move_dir.opposite()
        if c.can_move(back_dir):
            c.move(back_dir)
        return

    # Placement: place splitter or foundry
    cost_s, cost_f = c.get_splitter_cost()[0], c.get_foundry_cost()[0]

    left_pos = move_pos.add(move_dir.rotate_left().rotate_left())
    right_pos = move_pos.add(move_dir.rotate_right().rotate_right())
    foundry_pos = left_pos if on_core_border(left_pos, self.core_pos) else right_pos

    if (
        on_core_border(move_pos, self.core_pos)
        and not self.splitter_for_foundry
        and not is_tile_splitter(c, move_pos)
        and (c.get_tile_building_id(move_pos) is None or c.can_destroy(move_pos))
        and self.ti >= cost_s
    ):
        if c.get_tile_building_id(move_pos) is not None:
            c.destroy(move_pos)
        if c.can_build_splitter(move_pos, move_dir):
            c.build_splitter(move_pos, move_dir)
            self.splitter_for_foundry = True
        return
    elif (
        on_core_border(foundry_pos, self.core_pos)
        and self.splitter_for_foundry
        and not is_tile_foundry(c, foundry_pos)
        and (c.get_tile_building_id(foundry_pos) is None or c.can_destroy(foundry_pos))
        and self.ti >= cost_f
    ):
        if c.get_tile_building_id(foundry_pos) is not None:
            c.destroy(foundry_pos)
        if c.can_build_foundry(foundry_pos):
            c.build_foundry(foundry_pos)
            self.foundry_curr_placed = True
            self.foundry_placed_round = c.get_current_round()
        return
    elif not on_core_border(move_pos, self.core_pos) and c.can_move(move_dir):
        c.move(move_dir)
