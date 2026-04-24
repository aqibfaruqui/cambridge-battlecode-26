from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position

from utils.map.board import (
    action_radius,
    is_tile_conveyor,
    is_tile_foundry,
    on_core_border,
)
from utils.pathfinding.movement import DIRECTIONS_4, get_direction_4, on_map

if TYPE_CHECKING:
    from builders.harvester import Harvester


_FOUNDRY_OUTPUT_WAIT = 40
_CLEARABLE_FOR_FOUNDRY = {
    EntityType.CONVEYOR,
    EntityType.ROAD,
    EntityType.MARKER,
    EntityType.SPLITTER,
}


def _finish_foundry(self: Harvester) -> None:
    self.foundry_prev_placed = True
    self.foundry_curr_placed = False
    self.splitter_for_foundry = False
    self.state = type(self.state).SEEK


def _building_type(c: Controller, pos: Position) -> EntityType | None:
    build_id = c.get_tile_building_id(pos)
    return None if build_id is None else c.get_entity_type(build_id)


def _is_clearable_for_foundry(c: Controller, pos: Position) -> bool:
    build_type = _building_type(c, pos)
    return build_type is None or (
        build_type in _CLEARABLE_FOR_FOUNDRY and c.can_destroy(pos)
    )


def _try_clear(c: Controller, pos: Position) -> bool:
    build_id = c.get_tile_building_id(pos)
    if build_id is None:
        return True
    if not c.can_destroy(pos):
        return False
    c.destroy(pos)
    return c.get_tile_building_id(pos) is None


def _splitter_accepts_conveyor(c: Controller, pos: Position, move_dir: Direction) -> bool:
    build_id = c.get_tile_building_id(pos)
    return (
        build_id is not None
        and c.get_entity_type(build_id) == EntityType.SPLITTER
        and c.get_direction(build_id) == move_dir
    )


def _side_foundry_candidates(
    c: Controller,
    splitter_pos: Position,
    move_dir: Direction,
    core_pos: Position,
) -> list[Position]:
    candidates = [
        splitter_pos.add(move_dir.rotate_left().rotate_left()),
        splitter_pos.add(move_dir.rotate_right().rotate_right()),
    ]
    return [
        pos
        for pos in candidates
        if on_map(c, pos) and on_core_border(pos, core_pos)
    ]


def _best_foundry_pos(
    c: Controller,
    splitter_pos: Position,
    move_dir: Direction,
    core_pos: Position,
) -> Position | None:
    candidates = _side_foundry_candidates(c, splitter_pos, move_dir, core_pos)
    for pos in candidates:
        if is_tile_foundry(c, pos):
            return pos

    buildable: list[Position] = []
    clearable: list[Position] = []
    for pos in candidates:
        if c.get_tile_building_id(pos) is None:
            if c.can_build_foundry(pos):
                buildable.append(pos)
        elif _is_clearable_for_foundry(c, pos):
            clearable.append(pos)

    if buildable:
        return buildable[0]
    if clearable:
        return clearable[0]
    return None


def _move_toward_nearby_conveyor(c: Controller, pos: Position) -> bool:
    adjacent_options: list[Direction] = []
    for d in DIRECTIONS_4:
        neighbor = pos.add(d)
        if is_tile_conveyor(c, neighbor):
            adjacent_options.append(d)

    for d in adjacent_options:
        if c.can_move(d):
            c.move(d)
            return True

    conveyors = [
        tile
        for tile in c.get_nearby_tiles(action_radius["bot"])
        if tile != pos and is_tile_conveyor(c, tile)
    ]
    conveyors.sort(key=lambda tile: pos.distance_squared(tile))
    for tile in conveyors:
        step_dir = get_direction_4(pos, tile)
        if c.can_move(step_dir):
            c.move(step_dir)
            return True
    return False


def _placing_foundry(self: Harvester, c: Controller) -> None:
    pos = self.current_pos

    # Foundry placed: wait for axionite (or timeout), then leave the foundry/splitter in place.
    if self.foundry_curr_placed:
        rounds_waiting = c.get_current_round() - self.foundry_placed_round
        if self.ax <= 0 and rounds_waiting < _FOUNDRY_OUTPUT_WAIT:
            return
        _finish_foundry(self)
        return

    # Positioning: get onto a conveyor
    if not is_tile_conveyor(c, pos):
        _move_toward_nearby_conveyor(c, pos)
        return

    conveyor_id = c.get_tile_building_id(pos)
    move_dir = c.get_direction(conveyor_id)
    if move_dir is None or move_dir == Direction.CENTRE or move_dir not in DIRECTIONS_4:
        self.state = type(self.state).SEEK
        return
    move_pos = pos.add(move_dir)
    if not on_map(c, move_pos):
        self.state = type(self.state).SEEK
        return

    # Too close to core: back up
    if max(abs(move_pos.x - self.core_pos.x), abs(move_pos.y - self.core_pos.y)) < 2:
        back_dir = move_dir.opposite()
        if c.can_move(back_dir):
            c.move(back_dir)
        return

    # Placement: place splitter or foundry
    cost_s, cost_f = c.get_splitter_cost()[0], c.get_foundry_cost()[0]

    foundry_pos = _best_foundry_pos(c, move_pos, move_dir, self.core_pos)

    if foundry_pos is not None and is_tile_foundry(c, foundry_pos):
        _finish_foundry(self)
        return

    if _splitter_accepts_conveyor(c, move_pos, move_dir):
        self.splitter_for_foundry = True

    if (
        on_core_border(move_pos, self.core_pos)
        and not self.splitter_for_foundry
        and _is_clearable_for_foundry(c, move_pos)
        and self.ti >= cost_s
    ):
        if not _try_clear(c, move_pos):
            return
        if c.can_build_splitter(move_pos, move_dir):
            c.build_splitter(move_pos, move_dir)
            self.splitter_for_foundry = True
        return
    elif (
        foundry_pos is not None
        and self.splitter_for_foundry
        and not is_tile_foundry(c, foundry_pos)
        and _is_clearable_for_foundry(c, foundry_pos)
        and self.ti >= cost_f
    ):
        if not _try_clear(c, foundry_pos):
            return
        if c.can_build_foundry(foundry_pos):
            c.build_foundry(foundry_pos)
            self.foundry_curr_placed = True
            self.foundry_placed_round = c.get_current_round()
        return
    elif not on_core_border(move_pos, self.core_pos) and c.can_move(move_dir):
        c.move(move_dir)
