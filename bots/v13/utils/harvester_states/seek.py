from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, Controller

from utils.pathfinding.d_star import (
    DSTAR_CPU_DEADLINE_US,
    DStarLite,
    _SEEK_BLOCK_MASK,
)
from utils.map.raw_map_representation import ORE_AXIONITE, ORE_TITANIUM
from utils.pathfinding.movement import DIRECTIONS_4, _chebyshev, random_direction_4
from utils.comms.for_builder_bot import BuilderBotMessages, BuilderBotMessageType
from utils.healing import _find_damaged_conveyor

if TYPE_CHECKING:
    from builders.harvester import Harvester

_DEGENERATE_ROOM = 3
_EXPLORE_R_MIN = 4


def _read_nearby_claims(c: Controller) -> set[tuple[int, int]]:
    claimed: set[tuple[int, int]] = set()
    my_team = c.get_team()
    for mid in c.get_nearby_buildings():
        if c.get_entity_type(mid) != EntityType.MARKER:
            continue
        if c.get_team(mid) != my_team:
            continue
        value = c.get_marker_value(mid)
        msg_type = BuilderBotMessages.get_message_type(value)
        if msg_type == BuilderBotMessageType.CLAIM_ORE:
            target = BuilderBotMessages.decode_claim_ore(value)
        elif msg_type == BuilderBotMessageType.CLAIM_POSITION:
            target = BuilderBotMessages.decode_claim_position(value)
        else:
            continue
        claimed.add((target.x, target.y))
    return claimed


def _explore_r_max(self: Harvester) -> int:
    env = self.environment_map
    if env is None:
        return _EXPLORE_R_MIN
    return max(_EXPLORE_R_MIN, (max(env.width, env.height) + 1) // 2)


def _explore_lane(self: Harvester) -> tuple[str, int]:
    env = self.environment_map
    if env is None:
        return "x", 1

    cx, cy = self.core_pos.x, self.core_pos.y
    w, h = env.width, env.height

    x_splittable = cx > _DEGENERATE_ROOM and (w - 1 - cx) > _DEGENERATE_ROOM
    y_splittable = cy > _DEGENERATE_ROOM and (h - 1 - cy) > _DEGENERATE_ROOM

    spawn = self.spawn_pos if self.spawn_pos is not None else self.current_pos
    dx = spawn.x - cx
    dy = spawn.y - cy
    parity = getattr(self, "bot_id", 0) % 2

    if x_splittable and y_splittable:
        hbal = min(cx, w - 1 - cx)
        vbal = min(cy, h - 1 - cy)
        axis = "x" if hbal >= vbal else "y"
        offset = dx if axis == "x" else dy
        if abs(offset) <= 1:
            # Spawn too close to centre-line — differentiate by bot parity.
            return axis, 1 if parity == 0 else -1
        return axis, 1 if offset > 0 else -1

    if x_splittable:
        if abs(dx) <= 1:
            return "x", 1 if parity == 0 else -1
        return "x", 1 if dx > 0 else -1

    if y_splittable:
        if abs(dy) <= 1:
            return "y", 1 if parity == 0 else -1
        return "y", 1 if dy > 0 else -1

    # Corner core: split axes entirely by bot parity so they never overlap.
    if parity == 0:
        return "x", 1 if (w - 1 - cx) >= cx else -1
    else:
        return "y", 1 if (h - 1 - cy) >= cy else -1


def _seek_dynamic_blockers(self: Harvester, c: Controller) -> list[tuple[int, int]]:
    blocked: list[tuple[int, int]] = []
    my_id = c.get_id()
    for pos in c.get_nearby_tiles():
        if pos == self.current_pos:
            continue
        bot_id = c.get_tile_builder_bot_id(pos)
        if bot_id is None or bot_id == my_id:
            continue
        blocked.append((pos.x, pos.y))
    return blocked


def _best_ore_approach(
    self: Harvester,
    ore_pos: Position,
    origin: Position | None = None,
    c: Controller | None = None,
) -> Position | None:
    if origin is None:
        origin = self.current_pos
    env = self.environment_map
    if env is None:
        return None

    best_target = None
    best_dist = float("inf")
    for direction in DIRECTIONS_4:
        candidate = ore_pos.add(direction)
        if candidate == origin:
            return candidate
        if not env.in_bounds(candidate.x, candidate.y):
            continue
        if not env.is_seek_candidate(candidate.x, candidate.y):
            continue
        if c is not None and c.is_in_vision(candidate):
            occupier = c.get_tile_builder_bot_id(candidate)
            if occupier is not None and occupier != c.get_id():
                continue
        dist = _chebyshev(origin, candidate)
        if dist < best_dist:
            best_dist = dist
            best_target = candidate
    return best_target


def _pick_explore_target(
    self: Harvester,
    lane_axis: str,
    lane_sign: int,
    blocked: set[tuple[int, int]] | None = None,
) -> Position | None:
    """
    Ring-based exploration centered on the core.
    Tries R = R_MAX down to R_MIN; within each ring scores by:
      - unknown tile / unexplored-border bonus
      - lane-direction bias (differentiates bots)
      - proximity to current bot (stay close for defence)
    """
    env = self.environment_map
    if env is None:
        return None
    ox, oy = self.core_pos.x, self.core_pos.y
    bx, by = self.current_pos.x, self.current_pos.y
    blocked = blocked or set()
    explore_r_max = _explore_r_max(self)

    for R in range(explore_r_max, _EXPLORE_R_MIN - 1, -1):
        best: Position | None = None
        best_score = float("-inf")

        for dx in range(-R, R + 1):
            for dy in (-R, R) if abs(dx) < R else range(-R, R + 1):
                tx, ty = ox + dx, oy + dy
                if (tx, ty) == (bx, by) or (tx, ty) in blocked:
                    continue
                if not env.in_bounds(tx, ty):
                    continue
                if not env.is_seek_candidate(tx, ty):
                    continue

                # Unknown / underexplored bonus
                if env.is_unknown(tx, ty):
                    u_score = 40
                else:
                    u_score = 0
                    for nx, ny in (
                        (tx + 1, ty),
                        (tx - 1, ty),
                        (tx, ty + 1),
                        (tx, ty - 1),
                    ):
                        if env.in_bounds(nx, ny) and env.is_unknown(nx, ny):
                            u_score += 10

                # Lane bias — keeps two bots in different halves of the map
                along = (dx * lane_sign) if lane_axis == "x" else (dy * lane_sign)

                # Proximity to bot — prefer tiles the bot can reach quickly
                bot_dist = max(abs(tx - bx), abs(ty - by))

                score = along * 8 + u_score - bot_dist
                if score > best_score:
                    best_score = score
                    best = Position(tx, ty)

        if best is not None:
            return best
        # No passable tile at this R — reduce and retry (point 5)

    return None


def _pick_seek_target(
    self: Harvester,
    pos: Position,
    c: Controller,
    claimed: set[tuple[int, int]],
) -> tuple[Position | None, bool]:
    env = self.environment_map
    if env is None:
        return pos.add(random_direction_4()), False

    blocked = set(self.blacklisted_ores) | claimed
    if self._axionite_unlocked(c):
        ore = env.nearest_known_axionite(pos, blocked)
    else:
        ore = env.nearest_known_titanium(pos, blocked)
    if ore is not None:
        return ore, True

    lane_axis, lane_sign = _explore_lane(self)
    explore = _pick_explore_target(
        self,
        lane_axis,
        lane_sign,
        self.blacklisted_seek_targets | claimed,
    )
    return (
        (explore, False)
        if explore is not None
        else (pos.add(random_direction_4()), False)
    )


def _target_still_viable(
    self: Harvester,
    target: Position,
    is_ore_target: bool,
    c: Controller | None = None,
) -> bool:
    env = self.environment_map
    if env is None or not env.in_bounds(target.x, target.y):
        return False
    if is_ore_target:
        if self.foundry_prev_placed and env.tile(target.x, target.y) == ORE_AXIONITE:
            return False
        if c is not None and c.is_in_vision(target):
            occupier = c.get_tile_builder_bot_id(target)
            if occupier is not None and occupier != c.get_id():
                return False
        return env.tile(target.x, target.y) in (ORE_TITANIUM, ORE_AXIONITE)
    # Frontier target: keep it until we arrive; don't scan neighbors every turn.
    return target != self.current_pos


def _can_execute_seek_step(self: Harvester, c: Controller, move_dir: Direction) -> bool:
    next_pos = self.current_pos.add(move_dir)
    if c.can_move(move_dir):
        return True
    if not (
        0 <= next_pos.x < c.get_map_width() and 0 <= next_pos.y < c.get_map_height()
    ):
        return False
    if c.get_tile_env(next_pos) != Environment.EMPTY:
        return False
    build_id = c.get_tile_building_id(next_pos)
    if build_id is not None and c.get_entity_type(build_id) == EntityType.MARKER:
        return True
    return c.can_build_road(next_pos)


def _seek_direction(
    self: Harvester, c: Controller, move_target: Position
) -> Direction | None:
    w = c.get_map_width()
    h = c.get_map_height()
    if w <= 0 or h <= 0 or self.environment_map is None:
        return None

    if not (0 <= move_target.x < w and 0 <= move_target.y < h):
        move_target = Position(
            min(max(move_target.x, 0), w - 1), min(max(move_target.y, 0), h - 1)
        )

    goal = (move_target.x, move_target.y)
    if self.seek_planner is None or self.seek_planner_goal != goal:
        self.seek_planner = DStarLite(
            self.environment_map,
            move_target.x,
            move_target.y,
            block_mask=_SEEK_BLOCK_MASK,
        )
        self.seek_planner_goal = goal

    self.seek_planner.set_position(self.current_pos.x, self.current_pos.y)
    self.seek_planner.set_dynamic_blockers(
        _seek_dynamic_blockers(self, c),
        DSTAR_CPU_DEADLINE_US,
        c.get_cpu_time_elapsed,
    )
    self.seek_planner.notify_map_changes(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)

    move_dir = self.seek_planner.step(DSTAR_CPU_DEADLINE_US, c.get_cpu_time_elapsed)
    if (
        move_dir is not None
        and move_dir != Direction.CENTRE
        and _can_execute_seek_step(self, c, move_dir)
    ):
        return move_dir
    return None


def _seek(self: Harvester, c: Controller):
    if self._try_build_harvester(c):
        return

    if self.heal_target is not None:
        if not c.is_in_vision(self.heal_target):
            self.heal_target = None
        else:
            bid = c.get_tile_building_id(self.heal_target)
            if (
                bid is None
                or c.get_team(bid) != c.get_team()
                or c.get_entity_type(bid)
                not in (EntityType.CONVEYOR, EntityType.BRIDGE)
                or c.get_hp(bid) >= c.get_max_hp(bid)
            ):
                self.heal_target = None

    if self.heal_target is None:
        self.heal_target = _find_damaged_conveyor(c)

    if self.heal_target is not None:
        if self.current_pos.distance_squared(self.heal_target) <= 2:
            if c.get_action_cooldown() == 0 and c.can_heal(self.heal_target):
                c.heal(self.heal_target)
        else:
            self._advance(c, _seek_direction(self, c, self.heal_target))
        return

    claimed = _read_nearby_claims(c)

    if self.target_pos is None or not _target_still_viable(
        self, self.target_pos, self.seek_target_is_ore, c
    ):
        self.target_pos, self.seek_target_is_ore = _pick_seek_target(
            self, self.current_pos, c, claimed
        )
        if self.target_pos is None:
            return

    if self.seek_stall_target == self.target_pos:
        self.seek_target_turns += 1
    else:
        self.seek_stall_target = self.target_pos
        self.seek_target_turns = 1
    if self.seek_target_turns >= 25:
        key = (self.target_pos.x, self.target_pos.y)
        if self.seek_target_is_ore:
            self.blacklisted_ores.add(key)
        else:
            self.blacklisted_seek_targets.add(key)
        self.target_pos = None
        self.seek_target_is_ore = False
        self.seek_stall_target = None
        self.seek_target_turns = 0
        return

    move_target = self.target_pos
    if self.seek_target_is_ore:
        if c.is_in_vision(self.target_pos) and not self._is_valid_ore_target(
            c, self.target_pos
        ):
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
            return
        move_target = _best_ore_approach(self, self.target_pos, c=c)
        if move_target is None:
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
            return

    move_dir = _seek_direction(self, c, move_target)
    if move_dir is None:
        key = (self.target_pos.x, self.target_pos.y)
        if self.seek_target_is_ore:
            self.blacklisted_ores.add(key)
        else:
            self.blacklisted_seek_targets.add(key)
        self.target_pos = None
        self.seek_target_is_ore = False
        self.seek_stall_target = None
        self.seek_target_turns = 0
        return

    if self.seek_target_is_ore:
        claim_value = BuilderBotMessages.encode_claim_ore(self.target_pos)
    else:
        claim_value = BuilderBotMessages.encode_claim_position(self.target_pos)
    best_claim_tile = None
    best_claim_dist = float("inf")
    for _mp in c.get_nearby_tiles():
        if not c.can_place_marker(_mp):
            continue
        d = _chebyshev(_mp, self.target_pos)
        if d < best_claim_dist:
            best_claim_dist = d
            best_claim_tile = _mp
    if best_claim_tile is not None:
        c.place_marker(best_claim_tile, claim_value)

    self._advance(c, move_dir)
