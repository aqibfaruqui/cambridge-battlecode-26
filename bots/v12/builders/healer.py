from enum import Enum

from cambc import Controller, Direction, EntityType, Environment, Position

from utils.harvester_states.heal import (
    _best_coverage_tile,
    _critical_damaged,
)
from utils.harvester_states.seek import _seek_direction
from utils.healing import try_heal_nearby_bot, try_heal_nearby_building
from utils.map.raw_map_representation import EnvironmentMap
from utils.pathfinding.d_star import DStarLite


class HealState(Enum):
    __slots__ = ()

    PATROL = "patrol"


_RING_DIRECTIONS = [
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
    Direction.NORTH,
    Direction.NORTHEAST,
]


class Healer:
    def __init__(self, core_pos: Position):
        self.core_pos = core_pos
        self.core_id: int | None = None
        self.ring_idx = 0

        self.current_pos = Position(0, 0)
        self.ti = 0
        self.ax = 0

        self.heal_target: Position | None = None

        # D* Lite pathfinding state
        self.environment_map: EnvironmentMap | None = None
        self.seek_planner: DStarLite | None = None
        self.seek_planner_goal: tuple[int, int] | None = None

    def _ring_pos(self, idx: int) -> Position:
        return self.core_pos.add(_RING_DIRECTIONS[idx % len(_RING_DIRECTIONS)])

    def _resolve_core_id(self, c: Controller) -> None:
        bid = c.get_tile_building_id(self.core_pos)
        if bid is not None and c.get_entity_type(bid) == EntityType.CORE:
            self.core_id = bid

    def _align_ring_idx(self, c: Controller) -> None:
        me = c.get_position()
        offset = (me.x - self.core_pos.x, me.y - self.core_pos.y)
        for i, d in enumerate(_RING_DIRECTIONS):
            if d.delta() == offset:
                self.ring_idx = i
                return

    def _advance(self, c: Controller, move_dir: Direction | None) -> None:
        if move_dir is None:
            return
        move_pos = self.current_pos.add(move_dir)
        build_id = c.get_tile_building_id(move_pos)
        if build_id is not None and c.get_entity_type(build_id) == EntityType.MARKER and c.can_destroy(move_pos):
            c.destroy(move_pos)
        if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(move_dir):
            c.move(move_dir)

    def _patrol(self, c: Controller) -> None:
        if c.get_move_cooldown() > 0:
            return

        me = c.get_position()

        step1_idx = (self.ring_idx + 1) % len(_RING_DIRECTIONS)
        step1_pos = self._ring_pos(step1_idx)

        for step in (1, 2):
            next_idx = (self.ring_idx + step) % len(_RING_DIRECTIONS)
            next_pos = self._ring_pos(next_idx)
            if me.distance_squared(next_pos) > 2:
                continue
            direction = me.direction_to(next_pos)
            if direction == Direction.CENTRE:
                continue
            if c.can_move(direction):
                c.move(direction)
                self.ring_idx = next_idx
                return

        if c.is_in_vision(step1_pos) and c.get_tile_builder_bot_id(step1_pos) is not None:
            direction = me.direction_to(self.core_pos)
            if direction != Direction.CENTRE and c.can_move(direction):
                c.move(direction)
                self.ring_idx = step1_idx
                return

        if c.get_action_cooldown() == 0 and c.can_build_road(step1_pos):
            c.build_road(step1_pos)

    def _draw_debug(self, c: Controller) -> None:
        if self.heal_target is not None:
            c.draw_indicator_dot(self.current_pos, 60, 255, 100)
            c.draw_indicator_line(self.current_pos, self.heal_target, 60, 255, 100)
        else:
            c.draw_indicator_dot(self.current_pos, 0, 200, 255)

    def run(self, c: Controller):
        if self.core_id is None:
            self._resolve_core_id(c)

        self.current_pos = c.get_position()
        self.ti, self.ax = c.get_global_resources()
        self._align_ring_idx(c)

        if self.environment_map is None:
            self.environment_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        self.environment_map.update(c)

        damaged = _critical_damaged(c)

        # Re-validate committed target each turn.
        committed = self.heal_target
        if committed is not None and c.is_in_vision(committed):
            bid = c.get_tile_building_id(committed)
            if (
                bid is None
                or c.get_team(bid) != c.get_team()
                or c.get_hp(bid) / c.get_max_hp(bid) >= 0.8
            ):
                committed = None
        if committed is None and damaged:
            committed = damaged[0]
        self.heal_target = committed

        me = self.current_pos

        # Heal action: bots first (including self), then buildings.
        if not try_heal_nearby_bot(c, me):
            try_heal_nearby_building(c, me)

        # Movement: navigate toward best coverage tile via D* Lite; patrol ring when idle.
        if c.get_move_cooldown() == 0:
            if damaged:
                approach = _best_coverage_tile(c, me, damaged)
                if me.distance_squared(approach) > 0:
                    move_dir = _seek_direction(self, c, approach)  # type: ignore[arg-type]
                    self._advance(c, move_dir)
            else:
                self._patrol(c)

        self._draw_debug(c)
