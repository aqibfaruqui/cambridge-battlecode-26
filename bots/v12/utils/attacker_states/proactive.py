from __future__ import annotations

import random
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Environment, Position

from utils.attacker_states.state import AttackState
from utils.map.raw_map_representation import CORE_ENEMY, WALL
from utils.pathfinding.movement import DIRECTIONS_4, on_map

if TYPE_CHECKING:
    from builders.attacker import Attacker


_CORE_SEARCH_RADIUS_SQ = 50
_PROACTIVE_STUCK_TURNS = 25
_PROACTIVE_REACHED_RADIUS_SQ = 4
_RING_TURN_CAP = 8

STEP_ON = "step_on"
RING = "ring"
STEP_OFF = "step_off"
BUILD_HARVESTER = "build_harvester"
POSITION_TURRET = "position_turret"
BUILD_TURRET = "build_turret"


def _valid_exploration_point(self: Attacker, c: Controller, pos: Position) -> bool:
    if not (0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()):
        return False
    env = self._env_map
    if env is None:
        return True
    return env.tile(pos.x, pos.y) not in (WALL, CORE_ENEMY)


def _pick_random_exploration_point(self: Attacker, c: Controller) -> Position | None:
    ec = self.enemy_core_pos
    assert ec is not None
    choices: list[Position] = []
    for dx in range(-7, 8):
        for dy in range(-7, 8):
            if dx * dx + dy * dy > _CORE_SEARCH_RADIUS_SQ:
                continue
            pos = Position(ec.x + dx, ec.y + dy)
            if _valid_exploration_point(self, c, pos):
                choices.append(pos)
    if not choices:
        return None
    return random.choice(choices)


def _is_unharvested_titanium(c: Controller, pos: Position) -> bool:
    if not c.is_in_vision(pos):
        return False
    if c.get_tile_env(pos) != Environment.ORE_TITANIUM:
        return False
    bld_id = c.get_tile_building_id(pos)
    return bld_id is None or c.get_entity_type(bld_id) != EntityType.HARVESTER


def _pick_visible_titanium(self: Attacker, c: Controller) -> Position | None:
    ec = self.enemy_core_pos
    assert ec is not None
    best: Position | None = None
    best_score = float("inf")
    for tile in c.get_nearby_tiles():
        if tile.distance_squared(ec) > _CORE_SEARCH_RADIUS_SQ:
            continue
        if not _is_unharvested_titanium(c, tile):
            continue
        if tile != self.current_pos and not c.is_tile_passable(tile):
            continue
        bot_id = c.get_tile_builder_bot_id(tile)
        if bot_id is not None and bot_id != c.get_id():
            continue
        score = self.current_pos.distance_squared(tile)
        if score < best_score:
            best_score = score
            best = tile
    return best


def _reset_proactive_placing(self: Attacker) -> None:
    self.proactive_placing_ore_pos = None
    self.proactive_placing_exit_pos = None
    self.proactive_placing_sides_pending = []
    self.proactive_placing_phase = STEP_ON
    self.proactive_placing_ring_turns = 0
    self.proactive_turret_pos = None


def _abort_proactive_placing(self: Attacker) -> None:
    _reset_proactive_placing(self)
    self.proactive_target = None
    self.proactive_ore_target = False
    self._planner_goal = None


def _start_proactive_placing(self: Attacker, c: Controller, ore_pos: Position) -> None:
    self.proactive_placing_ore_pos = ore_pos
    self.proactive_placing_exit_pos = self.current_pos
    self.proactive_placing_sides_pending = list(DIRECTIONS_4)
    self.proactive_placing_phase = STEP_ON
    self.proactive_placing_ring_turns = 0
    self.proactive_turret_pos = None
    self.proactive_target = ore_pos
    self.proactive_ore_target = True
    self._proactive_pursuit_round = c.get_current_round()


def _proactive_target_still_valid(self: Attacker, c: Controller) -> bool:
    ore_pos = self.proactive_placing_ore_pos
    if ore_pos is None:
        return False
    phase = self.proactive_placing_phase
    if phase in {POSITION_TURRET, BUILD_TURRET}:
        if not c.is_in_vision(ore_pos):
            return True
        bid = c.get_tile_building_id(ore_pos)
        return bid is not None and c.get_entity_type(bid) == EntityType.HARVESTER
    return _is_unharvested_titanium(c, ore_pos)


def _do_step_on(self: Attacker, c: Controller, ore_pos: Position) -> None:
    move_dir = self.current_pos.direction_to(ore_pos)
    if move_dir not in DIRECTIONS_4:
        _abort_proactive_placing(self)
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
        self.current_pos = c.get_position()


def _do_ring(self: Attacker, c: Controller, ore_pos: Position) -> None:
    if self.current_pos != ore_pos:
        _abort_proactive_placing(self)
        return

    self.proactive_placing_ring_turns += 1
    built = False
    remaining: list[Direction] = []
    for side in self.proactive_placing_sides_pending:
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
    self.proactive_placing_sides_pending = remaining

    if (
        not self.proactive_placing_sides_pending
        or self.proactive_placing_ring_turns >= _RING_TURN_CAP
    ):
        self.proactive_placing_phase = STEP_OFF


def _do_step_off(self: Attacker, c: Controller, ore_pos: Position) -> None:
    if self.current_pos != ore_pos:
        self.proactive_placing_phase = BUILD_HARVESTER
        _finish_harvester(self, c, ore_pos)
        return

    exit_pos = self.proactive_placing_exit_pos
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
        self.current_pos = c.get_position()
        return

    for d in DIRECTIONS_4:
        if d == preferred:
            continue
        if c.can_move(d) and _tile_is_open(d):
            c.move(d)
            self.current_pos = c.get_position()
            return


def _finish_harvester(self: Attacker, c: Controller, ore_pos: Position) -> None:
    if self.current_pos == ore_pos:
        self.proactive_placing_phase = STEP_OFF
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
    self.proactive_placing_phase = POSITION_TURRET


def _enemy_builder_bot_in_vision(c: Controller) -> Position | None:
    my_team = c.get_team()
    best: Position | None = None
    best_dist = float("inf")
    me = c.get_position()
    for eid in c.get_nearby_entities():
        if c.get_team(eid) == my_team:
            continue
        if c.get_entity_type(eid) != EntityType.BUILDER_BOT:
            continue
        pos = c.get_position(eid)
        dist = me.distance_squared(pos)
        if dist < best_dist:
            best_dist = dist
            best = pos
    return best


def _pick_turret_pos(self: Attacker, c: Controller, ore_pos: Position) -> Position | None:
    ec = self.enemy_core_pos
    sides = list(DIRECTIONS_4)
    my_id = c.get_id()
    if ec is not None:
        sides.sort(key=lambda d: ore_pos.add(d).distance_squared(ec))

    for side in sides:
        pos = ore_pos.add(side)
        if not on_map(c, pos):
            continue
        bot_id = c.get_tile_builder_bot_id(pos)
        if bot_id is not None and bot_id != my_id:
            continue
        bid = c.get_tile_building_id(pos)
        if bid is not None and c.get_entity_type(bid) == EntityType.CONVEYOR:
            return pos
    return None


def _stand_positions_for_turret(c: Controller, turret_pos: Position, ore_pos: Position) -> list[Position]:
    positions: list[Position] = []
    my_id = c.get_id()
    me = c.get_position()
    for d in DIRECTIONS_4:
        pos = turret_pos.add(d)
        if pos == turret_pos or pos == ore_pos:
            continue
        if not on_map(c, pos):
            continue
        if c.get_tile_env(pos) != Environment.EMPTY:
            continue
        bot_id = c.get_tile_builder_bot_id(pos)
        if bot_id is not None and bot_id != my_id:
            continue
        bid = c.get_tile_building_id(pos)
        if bid is not None and pos != me and not c.is_tile_passable(pos):
            continue
        positions.append(pos)
    return positions


def _position_for_turret(self: Attacker, c: Controller, ore_pos: Position) -> None:
    turret_pos = self.proactive_turret_pos
    if turret_pos is None:
        turret_pos = _pick_turret_pos(self, c, ore_pos)
        if turret_pos is None:
            _reset_proactive_placing(self)
            self.proactive_target = None
            self.proactive_ore_target = False
            self._planner_goal = None
            return
        self.proactive_turret_pos = turret_pos

    me = c.get_position()
    self.current_pos = me
    stand_positions = _stand_positions_for_turret(c, turret_pos, ore_pos)
    if me in stand_positions:
        self.proactive_placing_phase = BUILD_TURRET
        _build_turret(self, c, ore_pos)
        return

    if not stand_positions:
        return

    stand_positions.sort(key=lambda p: me.distance_squared(p))
    stand_pos = stand_positions[0]
    self.target_pos = stand_pos
    c.draw_indicator_line(me, stand_pos, 255, 255, 0)

    move_dir = me.direction_to(stand_pos)
    if (
        move_dir != Direction.CENTRE
        and max(abs(me.x - stand_pos.x), abs(me.y - stand_pos.y)) <= 1
        and c.is_in_vision(stand_pos)
    ):
        if c.get_tile_building_id(stand_pos) is None and c.can_build_road(stand_pos):
            c.build_road(stand_pos)
        if c.can_move(move_dir):
            c.move(move_dir)
            self.current_pos = c.get_position()
            return

    self._search(c, stand_pos)
    self.current_pos = c.get_position()


def _build_turret(self: Attacker, c: Controller, ore_pos: Position) -> None:
    turret_pos = self.proactive_turret_pos
    if turret_pos is None:
        self.proactive_placing_phase = POSITION_TURRET
        return

    me = c.get_position()
    self.current_pos = me
    if me not in _stand_positions_for_turret(c, turret_pos, ore_pos):
        self.proactive_placing_phase = POSITION_TURRET
        return

    enemy_builder = _enemy_builder_bot_in_vision(c)
    use_gunner = enemy_builder is not None
    facing_target = enemy_builder if enemy_builder is not None else self.enemy_core_pos
    if facing_target is None:
        return
    facing = turret_pos.direction_to(facing_target)
    if facing == Direction.CENTRE:
        facing = me.direction_to(turret_pos)

    turret_cost, can_build_turret, build_turret = (
        (c.get_gunner_cost(), c.can_build_gunner, c.build_gunner)
        if use_gunner
        else (c.get_sentinel_cost(), c.can_build_sentinel, c.build_sentinel)
    )

    bid = c.get_tile_building_id(turret_pos)
    if bid is not None:
        if c.get_entity_type(bid) not in {EntityType.CONVEYOR, EntityType.ROAD, EntityType.MARKER}:
            _abort_proactive_placing(self)
            return
        resources = c.get_global_resources()
        if (
            resources[0] < turret_cost[0]
            or resources[1] < turret_cost[1]
            or not c.can_destroy(turret_pos)
        ):
            return
        c.destroy(turret_pos)

    if can_build_turret(turret_pos, facing):
        build_turret(turret_pos, facing)
        _reset_proactive_placing(self)
        self.proactive_target = None
        self.proactive_ore_target = False
        self._planner_goal = None


def _continue_proactive_placing(self: Attacker, c: Controller) -> None:
    if not _proactive_target_still_valid(self, c):
        _abort_proactive_placing(self)
        return

    ore_pos = self.proactive_placing_ore_pos
    assert ore_pos is not None

    if self.proactive_placing_phase == STEP_ON and self.current_pos == ore_pos:
        self.proactive_placing_phase = RING

    phase = self.proactive_placing_phase
    if phase == STEP_ON:
        _do_step_on(self, c, ore_pos)
    elif phase == RING:
        _do_ring(self, c, ore_pos)
    elif phase == STEP_OFF:
        _do_step_off(self, c, ore_pos)
    elif phase == BUILD_HARVESTER:
        _finish_harvester(self, c, ore_pos)
    elif phase == POSITION_TURRET:
        _position_for_turret(self, c, ore_pos)
    elif phase == BUILD_TURRET:
        _build_turret(self, c, ore_pos)
    else:
        _abort_proactive_placing(self)


def proactive(self: Attacker, c: Controller) -> None:
    """Explore near the enemy core until we can stand on unharvested titanium."""
    if self.enemy_core_pos is None:
        self.proactive_target = None
        self.proactive_ore_target = False
        _reset_proactive_placing(self)
        self.state = AttackState.SCAN
        return

    self.current_pos = c.get_position()
    if self.proactive_placing_ore_pos is not None:
        _continue_proactive_placing(self, c)
        return

    ore = _pick_visible_titanium(self, c)
    if ore is not None:
        self.proactive_target = ore
        self.proactive_ore_target = True
        self._proactive_pursuit_round = c.get_current_round()
    elif self.proactive_ore_target:
        target = self.proactive_target
        if target is None or (c.is_in_vision(target) and not _is_unharvested_titanium(c, target)):
            self.proactive_target = None
            self.proactive_ore_target = False

    target = self.proactive_target
    round_now = c.get_current_round()
    if (
        target is None
        or (not self.proactive_ore_target and self.current_pos.distance_squared(target) <= _PROACTIVE_REACHED_RADIUS_SQ)
        or round_now - self._proactive_pursuit_round >= _PROACTIVE_STUCK_TURNS
    ):
        target = _pick_random_exploration_point(self, c)
        self.proactive_target = target
        self.proactive_ore_target = False
        self._proactive_pursuit_round = round_now

    if target is None:
        return

    self.target_pos = target
    c.draw_indicator_line(self.current_pos, target, 0, 255, 255)
    if (
        self.proactive_ore_target
        and (
            self.current_pos == target
            or self.current_pos.direction_to(target) in DIRECTIONS_4
        )
    ):
        _start_proactive_placing(self, c, target)
        _continue_proactive_placing(self, c)
        return

    self._search(c, target)
    self.current_pos = c.get_position()

    if self.proactive_ore_target and c.get_position() == target:
        _start_proactive_placing(self, c, target)
        _continue_proactive_placing(self, c)
