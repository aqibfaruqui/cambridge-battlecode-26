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
    FOLLOW = "follow"


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
        self.state = HealState.PATROL
        self.follow_enemy_id: int | None = None
        self.follow_enemy_last_pos: Position | None = None

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

    def _enemy_builder_pos(self, c: Controller, enemy_id: int) -> Position | None:
        for uid in c.get_nearby_units():
            if uid == enemy_id:
                return c.get_position(uid)
        return None

    def _has_adjacent_ally_builder(
        self, c: Controller, enemy_pos: Position, my_team
    ) -> bool:
        for uid in c.get_nearby_units():
            if c.get_team(uid) != my_team:
                continue
            if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            if enemy_pos.distance_squared(c.get_position(uid)) <= 2:
                return True
        return False

    def _pick_unhandled_enemy_builder(self, c: Controller) -> tuple[int, Position] | None:
        me = self.current_pos
        my_team = c.get_team()
        best: tuple[int, Position] | None = None
        best_d = float("inf")
        for uid in c.get_nearby_units():
            if c.get_team(uid) == my_team:
                continue
            if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            pos = c.get_position(uid)
            if self._has_adjacent_ally_builder(c, pos, my_team):
                continue
            d = me.distance_squared(pos)
            if d < best_d:
                best = (uid, pos)
                best_d = d
        return best

    def _try_enter_follow(self, c: Controller) -> bool:
        if self.follow_enemy_id is not None:
            return False
        target = self._pick_unhandled_enemy_builder(c)
        if target is None:
            return False
        self.follow_enemy_id, self.follow_enemy_last_pos = target
        self.state = HealState.FOLLOW
        self.seek_planner = None
        self.seek_planner_goal = None
        return True

    def _follow_approach_pos(self, c: Controller, enemy_pos: Position) -> Position:
        me = self.current_pos
        best = enemy_pos
        best_d = me.distance_squared(enemy_pos)
        w, h = c.get_map_width(), c.get_map_height()
        for direction in _RING_DIRECTIONS:
            candidate = enemy_pos.add(direction)
            if not (0 <= candidate.x < w and 0 <= candidate.y < h):
                continue
            if c.is_in_vision(candidate):
                occupier = c.get_tile_builder_bot_id(candidate)
                if occupier is not None and occupier != c.get_id():
                    continue
                if c.get_tile_env(candidate) != Environment.EMPTY:
                    continue
            d = me.distance_squared(candidate)
            if d < best_d:
                best = candidate
                best_d = d
        return best

    def _follow(self, c: Controller) -> None:
        enemy_id = self.follow_enemy_id
        if enemy_id is None:
            return

        enemy_pos = self._enemy_builder_pos(c, enemy_id)
        if enemy_pos is not None:
            self.follow_enemy_last_pos = enemy_pos
        target = self.follow_enemy_last_pos
        if target is None or c.get_move_cooldown() > 0:
            return

        me = self.current_pos
        if enemy_pos is not None and me.distance_squared(enemy_pos) <= 2:
            return

        approach = self._follow_approach_pos(c, target)
        if me.distance_squared(approach) == 0:
            return
        move_dir = _seek_direction(self, c, approach)  # type: ignore[arg-type]
        self._advance(c, move_dir)

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

        if self.state == HealState.PATROL:
            self._try_enter_follow(c)

        if self.state == HealState.FOLLOW:
            self._follow(c)
            self._draw_debug(c)
            return

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
