from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Environment, Position

from utils.axioniter_states.return_to_core import _reset_return_state
from utils.pathfinding.movement import DIRECTIONS_4, on_map

if TYPE_CHECKING:
    from builders.axioniter import Axioniter


STEP_ON = "step_on"
RING = "ring"
STEP_OFF = "step_off"
BUILD = "build"

# Cap time spent ringing so permanently-blocked sides can't strand us on the ore.
_RING_TURN_CAP = 8


def _reset_placing_state(self: Axioniter) -> None:
    self.placing_ore_pos = None
    self.placing_exit_pos = None
    self.placing_sides_pending = []
    self.placing_phase = STEP_ON
    self.placing_ring_turns = 0
    self.placing_is_titanium = False


def _abort_to_seek(self: Axioniter) -> None:
    _reset_placing_state(self)
    self.state = type(self.state).SEEK


def _target_still_valid(self: Axioniter, c: Controller) -> bool:
    ore_pos = self.placing_ore_pos
    if ore_pos is None:
        return False
    return self._is_valid_axionite_target(c, ore_pos)


def _finish_build(self: Axioniter, c: Controller) -> None:
    ore_pos = self.placing_ore_pos
    if ore_pos is None:
        _abort_to_seek(self)
        return

    build_id = c.get_tile_building_id(ore_pos)
    if (
        build_id is not None
        and c.get_entity_type(build_id)
        in {EntityType.ROAD, EntityType.CONVEYOR, EntityType.MARKER}
        and c.can_destroy(ore_pos)
        and c.get_global_resources()[0] >= c.get_harvester_cost()[0]
    ):
        c.destroy(ore_pos)

    if not c.can_build_harvester(ore_pos):
        return

    c.build_harvester(ore_pos)
    self.harvesters_placed += 1
    self.axionite_harvesters_placed += 1
    self.axionite_found = True
    self.returning_from_axionite = True
    self.blacklisted_ores.discard((ore_pos.x, ore_pos.y))
    self.target_pos = None
    self.seek_target_is_ore = False
    self.harvester_pos = ore_pos
    self.just_placed = True
    _reset_return_state(self)
    _reset_placing_state(self)
    self.state = type(self.state).RETURN


def _do_step_on(self: Axioniter, c: Controller, ore_pos: Position) -> None:
    move_dir = self.current_pos.direction_to(ore_pos)
    if move_dir not in DIRECTIONS_4:
        _abort_to_seek(self)
        return

    build_id = c.get_tile_building_id(ore_pos)
    if (
        build_id is not None
        and c.get_entity_type(build_id) == EntityType.MARKER
        and c.can_destroy(ore_pos)
    ):
        c.destroy(ore_pos)
        build_id = None

    if build_id is None and c.can_build_road(ore_pos):
        c.build_road(ore_pos)

    if c.can_move(move_dir):
        c.move(move_dir)


def _do_ring(self: Axioniter, c: Controller, ore_pos: Position) -> None:
    if self.current_pos != ore_pos:
        _abort_to_seek(self)
        return

    self.placing_ring_turns += 1
    built = False
    remaining: list[Direction] = []
    for side in self.placing_sides_pending:
        if built:
            remaining.append(side)
            continue
        side_pos = ore_pos.add(side)
        if not on_map(c, side_pos):
            continue
        flow = side.opposite()
        bid = c.get_tile_building_id(side_pos)
        if (
            bid is not None
            and c.get_entity_type(bid) in {EntityType.MARKER, EntityType.ROAD}
            and c.can_destroy(side_pos)
            and c.get_global_resources()[0] >= c.get_conveyor_cost()[0]
        ):
            c.destroy(side_pos)
        if c.can_build_conveyor(side_pos, flow):
            c.build_conveyor(side_pos, flow)
            built = True
    self.placing_sides_pending = remaining

    if not self.placing_sides_pending or self.placing_ring_turns >= _RING_TURN_CAP:
        self.placing_phase = STEP_OFF


def _do_step_off(self: Axioniter, c: Controller, ore_pos: Position) -> None:
    if self.current_pos != ore_pos:
        self.placing_phase = BUILD
        _finish_build(self, c)
        return

    exit_pos = self.placing_exit_pos
    preferred: Direction | None = None
    if exit_pos is not None:
        d = ore_pos.direction_to(exit_pos)
        if d in DIRECTIONS_4:
            preferred = d

    def _tile_is_open(move_dir: Direction) -> bool:
        next_pos = ore_pos.add(move_dir)
        return (
            c.get_tile_env(next_pos) == Environment.EMPTY
            and c.get_tile_builder_bot_id(next_pos) is None
        )

    if preferred is not None and c.can_move(preferred) and _tile_is_open(preferred):
        c.move(preferred)
        return

    for d in DIRECTIONS_4:
        if d == preferred:
            continue
        if c.can_move(d) and _tile_is_open(d):
            c.move(d)
            return


def _do_build(self: Axioniter, c: Controller, ore_pos: Position) -> None:
    if self.current_pos == ore_pos:
        self.placing_phase = STEP_OFF
        return
    _finish_build(self, c)


def _placing_harvester(self: Axioniter, c: Controller) -> None:
    if not _target_still_valid(self, c):
        _abort_to_seek(self)
        return

    ore_pos = self.placing_ore_pos
    assert ore_pos is not None

    # Re-sync phase to current position so we don't rebuild road / re-enter
    # step_on after an earlier turn successfully moved us onto the ore.
    if self.placing_phase == STEP_ON and self.current_pos == ore_pos:
        self.placing_phase = RING

    phase = self.placing_phase
    if phase == STEP_ON:
        _do_step_on(self, c, ore_pos)
    elif phase == RING:
        _do_ring(self, c, ore_pos)
    elif phase == STEP_OFF:
        _do_step_off(self, c, ore_pos)
    elif phase == BUILD:
        _do_build(self, c, ore_pos)
    else:
        _abort_to_seek(self)
