import random
from enum import Enum

from cambc import Controller, Direction, EntityType, Environment, Position

from utils.harvester_states.heal import (
    _best_coverage_tile,
    _critical_damaged,
)
from utils.harvester_states.seek import _seek_direction
from utils.healing import (
    try_heal_adjacent_most_missing,
    try_heal_nearby_bot,
    try_heal_nearby_building,
)
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

_PATROL_REACHED_DIST_SQ = 8
_PATROL_MIN_CORE_DIST = 4
_PATROL_MIN_RADIUS_FRACTION = 2
_PATROL_STUCK_TURNS = 8
_PATROL_TARGET_ATTEMPTS = 24


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
        self.patrol_target: Position | None = None
        self.patrol_last_pos: Position | None = None
        self.patrol_stuck_turns = 0

        # D* Lite pathfinding state
        self.environment_map: EnvironmentMap | None = None
        self.seek_planner: DStarLite | None = None
        self.seek_planner_goal: tuple[int, int] | None = None

    def _ring_pos(self, idx: int) -> Position:
        return self.core_pos.add(_RING_DIRECTIONS[idx % len(_RING_DIRECTIONS)])

    def _patrol_radius(self, c: Controller) -> int:
        return max(1, max(c.get_map_width(), c.get_map_height()) // 2)

    def _is_patrol_candidate(self, c: Controller, pos: Position) -> bool:
        if not (0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()):
            return False
        if self._is_enemy_launcher_danger(c, pos):
            return False
        dx = pos.x - self.core_pos.x
        dy = pos.y - self.core_pos.y
        if max(abs(dx), abs(dy)) < _PATROL_MIN_CORE_DIST:
            return False
        radius = self._patrol_radius(c)
        dist_sq = dx * dx + dy * dy
        min_radius = max(_PATROL_MIN_CORE_DIST, radius // _PATROL_MIN_RADIUS_FRACTION)
        if dist_sq < min_radius * min_radius or dist_sq > radius * radius:
            return False
        env = self.environment_map
        return env is None or env.is_seek_candidate(pos.x, pos.y)

    def _pick_patrol_target(self, c: Controller) -> Position | None:
        radius = self._patrol_radius(c)
        for _ in range(_PATROL_TARGET_ATTEMPTS):
            dx = random.randint(-radius, radius)
            dy = random.randint(-radius, radius)
            candidate = Position(self.core_pos.x + dx, self.core_pos.y + dy)
            if self._is_patrol_candidate(c, candidate):
                return candidate

        best: Position | None = None
        best_dist = -1
        for x in range(c.get_map_width()):
            for y in range(c.get_map_height()):
                candidate = Position(x, y)
                if not self._is_patrol_candidate(c, candidate):
                    continue
                dist = self.current_pos.distance_squared(candidate)
                if dist > best_dist:
                    best = candidate
                    best_dist = dist
        return best

    def _set_patrol_target(self, c: Controller) -> None:
        self.patrol_target = self._pick_patrol_target(c)
        self.patrol_last_pos = self.current_pos
        self.patrol_stuck_turns = 0

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
        if self._is_enemy_launcher_danger(c, move_pos):
            return
        build_id = c.get_tile_building_id(move_pos)
        if build_id is not None and c.get_entity_type(build_id) == EntityType.MARKER and c.can_destroy(move_pos):
            c.destroy(move_pos)
        if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(move_dir):
            c.move(move_dir)

    def _is_enemy_launcher_danger(self, c: Controller, pos: Position) -> bool:
        my_team = c.get_team()
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == my_team:
                continue
            if c.get_entity_type(bid) != EntityType.LAUNCHER:
                continue
            if pos.distance_squared(c.get_position(bid)) <= 2:
                return True
        return False

    def _extra_seek_dynamic_blockers(self, c: Controller) -> list[tuple[int, int]]:
        blockers: list[tuple[int, int]] = []
        my_team = c.get_team()
        w, h = c.get_map_width(), c.get_map_height()
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) == my_team:
                continue
            if c.get_entity_type(bid) != EntityType.LAUNCHER:
                continue
            launcher_pos = c.get_position(bid)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    x, y = launcher_pos.x + dx, launcher_pos.y + dy
                    if 0 <= x < w and 0 <= y < h:
                        blockers.append((x, y))
        return blockers

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

    def _reset_follow_to_patrol(self) -> None:
        self.follow_enemy_id = None
        self.follow_enemy_last_pos = None
        self.state = HealState.PATROL
        self.seek_planner = None
        self.seek_planner_goal = None
        self.patrol_target = None

    def _has_adjacent_different_enemy_builder(
        self, c: Controller, tracked_enemy_id: int
    ) -> bool:
        me = self.current_pos
        my_team = c.get_team()
        for uid in c.get_nearby_units():
            if uid == tracked_enemy_id:
                continue
            if c.get_team(uid) == my_team:
                continue
            if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            if me.distance_squared(c.get_position(uid)) <= 2:
                return True
        return False

    def _should_drop_follow_target(
        self, c: Controller, enemy_id: int, enemy_pos: Position | None
    ) -> bool:
        if not self._has_adjacent_different_enemy_builder(c, enemy_id):
            return False
        return enemy_pos is None or self.current_pos.distance_squared(enemy_pos) > 2

    def _follow_approach_pos(self, c: Controller, enemy_pos: Position) -> Position:
        me = self.current_pos
        best = enemy_pos
        best_d = me.distance_squared(enemy_pos)
        w, h = c.get_map_width(), c.get_map_height()
        for direction in _RING_DIRECTIONS:
            candidate = enemy_pos.add(direction)
            if not (0 <= candidate.x < w and 0 <= candidate.y < h):
                continue
            if self._is_enemy_launcher_danger(c, candidate):
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
        if self._should_drop_follow_target(c, enemy_id, enemy_pos):
            self._reset_follow_to_patrol()
            return
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
        target = self.patrol_target

        if target is not None and me.distance_squared(target) <= _PATROL_REACHED_DIST_SQ:
            target = None

        if target is not None and not self._is_patrol_candidate(c, target):
            target = None

        if self.patrol_last_pos == me:
            self.patrol_stuck_turns += 1
        else:
            self.patrol_stuck_turns = 0
            self.patrol_last_pos = me

        if self.patrol_stuck_turns >= _PATROL_STUCK_TURNS:
            target = None

        if target is None:
            self._set_patrol_target(c)
            target = self.patrol_target
            if target is None:
                return

        move_dir = _seek_direction(self, c, target)  # type: ignore[arg-type]
        if move_dir is None:
            self.patrol_stuck_turns += 1
            if self.patrol_stuck_turns >= _PATROL_STUCK_TURNS:
                self._set_patrol_target(c)
            return
        self._advance(c, move_dir)

    def _draw_debug(self, c: Controller) -> None:
        if self.follow_enemy_last_pos is not None:
            c.draw_indicator_line(self.current_pos, self.follow_enemy_last_pos, 0, 0, 0)
        if self.heal_target is not None:
            c.draw_indicator_dot(self.current_pos, 60, 255, 100)
            c.draw_indicator_line(self.current_pos, self.heal_target, 60, 255, 100)
        else:
            c.draw_indicator_dot(self.current_pos, 0, 200, 255)

    def _log_turn_state(self, c: Controller) -> None:
        patrol_target = self.patrol_target
        heal_target = self.heal_target
        follow_pos = self.follow_enemy_last_pos
        print(
            f"[healer {c.get_id()}] r={c.get_current_round()} "
            f"state={self.state.value} "
            f"patrol_target={((patrol_target.x, patrol_target.y) if patrol_target else '-')} "
            f"stuck={self.patrol_stuck_turns} "
            f"heal_target={((heal_target.x, heal_target.y) if heal_target else '-')} "
            f"follow_enemy={self.follow_enemy_id if self.follow_enemy_id is not None else '-'} "
            f"follow_pos={((follow_pos.x, follow_pos.y) if follow_pos else '-')}",
        )

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

        # Heal action: adjacent damaged tiles first, then existing bot/building fallbacks.
        if not try_heal_adjacent_most_missing(c, me) and not try_heal_nearby_bot(c, me):
            try_heal_nearby_building(c, me)

        if self.state == HealState.PATROL:
            self._try_enter_follow(c)

        if self.state == HealState.FOLLOW:
            self._follow(c)
            if self.state == HealState.PATROL:
                self._try_enter_follow(c)
            if self.state == HealState.FOLLOW:
                self._draw_debug(c)
                self._log_turn_state(c)
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
        self._log_turn_state(c)
