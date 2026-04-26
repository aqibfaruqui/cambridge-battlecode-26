from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Environment, Position, ResourceType

from utils.pathfinding.movement import DIRECTIONS_4, on_map

if TYPE_CHECKING:
    from builders.harvester import Harvester


def _allied_conveyor_at(c: Controller, pos: Position) -> int | None:
    if not on_map(c, pos) or not c.is_in_vision(pos):
        return None
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return None
    if c.get_team(bid) != c.get_team():
        return None
    if c.get_entity_type(bid) != EntityType.CONVEYOR:
        return None
    return bid


def _near_allied_harvester(c: Controller, pos: Position) -> bool:
    for d in DIRECTIONS_4:
        neighbor = pos.add(d)
        if not on_map(c, neighbor) or not c.is_in_vision(neighbor):
            continue
        bid = c.get_tile_building_id(neighbor)
        if (
            bid is not None
            and c.get_team(bid) == c.get_team()
            and c.get_entity_type(bid) == EntityType.HARVESTER
        ):
            return True
    return False


def _ti_input_count(c: Controller, join_pos: Position, exclude_dir: Direction) -> int:
    count = 0
    for d in DIRECTIONS_4:
        if d == exclude_dir:
            continue
        src = join_pos.add(d.opposite())
        if not on_map(c, src) or not c.is_in_vision(src):
            continue
        bid = _allied_conveyor_at(c, src)
        if bid is not None and c.get_direction(bid) == d:
            count += 1
    return count


def _is_valid_join_pos(self: Harvester, c: Controller, join_pos: Position) -> bool:
    if _near_allied_harvester(c, join_pos):
        return False

    join_id = _allied_conveyor_at(c, join_pos)
    if join_id is None:
        return False

    if c.get_stored_resource(join_id) == ResourceType.RAW_AXIONITE:
        return False

    feed_dir = self.current_pos.direction_to(join_pos)
    if feed_dir not in DIRECTIONS_4:
        return False

    if c.get_direction(join_id) not in DIRECTIONS_4:
        return False

    ti_inputs = _ti_input_count(c, join_pos, exclude_dir=feed_dir)
    if ti_inputs > 1:
        return False

    return True


def _finish_foundry_join(self: Harvester, c: Controller, join_pos: Position) -> None:
    self.foundry_curr_placed = True
    self.foundry_prev_placed = True
    self.foundry_placed_round = c.get_current_round()
    self.returning_from_axionite = False
    self.target_pos = None
    self.seek_target_is_ore = False
    self.harvester_pos = None
    self.chain_memory.pop((join_pos.x, join_pos.y), None)
    self.bridge_jump_target = None
    self.bridge_target_planner = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}
    self.state = type(self.state).SEEK


def try_join_axionite_to_titanium_chain(
    self: Harvester, c: Controller, join_pos: Position
) -> bool:
    if not self.returning_from_axionite:
        return False
    if self.foundry_prev_placed:
        return False

    if not _is_valid_join_pos(self, c, join_pos):
        return False

    join_id = _allied_conveyor_at(c, join_pos)
    if join_id is None:
        return False

    original_dir = c.get_direction(join_id)
    feed_dir = self.current_pos.direction_to(join_pos)

    current_id = c.get_tile_building_id(self.current_pos)
    if current_id is not None and c.get_entity_type(current_id) in (EntityType.MARKER, EntityType.ROAD):
        if c.can_destroy(self.current_pos):
            c.destroy(self.current_pos)
        return True
    if current_id is None and c.get_tile_env(self.current_pos) == Environment.EMPTY:
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if self.ti >= conveyor_cost_ti and c.can_build_conveyor(self.current_pos, feed_dir):
            c.build_conveyor(self.current_pos, feed_dir)
        return True

    feeds_ok = (
        current_id is not None
        and c.get_entity_type(current_id) == EntityType.CONVEYOR
        and c.get_team(current_id) == c.get_team()
        and c.get_direction(current_id) == feed_dir
    )
    if not feeds_ok:
        return False

    foundry_cost_ti, _ = c.get_foundry_cost()
    if self.ti < foundry_cost_ti:
        return True

    if not c.can_destroy(join_pos):
        return False

    c.destroy(join_pos)
    if c.can_build_foundry(join_pos):
        c.build_foundry(join_pos)
        _finish_foundry_join(self, c, join_pos)
        return True

    if c.can_build_conveyor(join_pos, original_dir):
        c.build_conveyor(join_pos, original_dir)
    self.returning_from_axionite = False
    return False
