from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Direction, Environment, Position, Controller

from utils.d_star import DStarLite, _SEEK_BLOCK_MASK
from utils.raw_map_representation import ORE_TITANIUM
from utils.movement import DIRECTIONS_4, _chebyshev, random_direction_4

if TYPE_CHECKING:
    from builders.harvester_revamped import Harvester


def _ensure_seek_blacklists(self) -> None:
    if not hasattr(self, "blacklisted_seek_targets"):
        self.blacklisted_seek_targets = set()
    if not hasattr(self, "seek_unreachable_counts"):
        self.seek_unreachable_counts = {}


def _seek_dynamic_blockers(self: Harvester, c: Controller, move_target: Position) -> list[tuple[int, int]]:
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


def _is_memory_passable(self: Harvester, x: int, y: int) -> bool:
    env = self.environment_map
    if env is None or not env.in_bounds(x, y):
        return False
    return env.is_frontier_passable(x, y)


def _best_ore_approach(
    self: Harvester, 
    ore_pos: Position, 
    origin: Position | None = None, 
    c: Controller | None = None
) -> Position | None:
    """Pick the best adjacent tile from which to build the harvester"""
    if origin is None:
        origin = self.current_pos
    env = self.environment_map
    if env is None:
        return None

    best_target = None
    best_dist = float("inf")

    # Choose the closest viable cardinal build tile around the ore.
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


def _frontier_score(self: Harvester, pos: Position, target: Position) -> float:
    """Score a frontier tile by exploration value and nearby ore density"""
    env = self.environment_map
    if env is None:
        return float("-inf")

    distance = pos.distance_squared(target) or 1
    unknown_neighbors = 0
    ore_neighbors = 0

    for direction in DIRECTIONS_4:
        neighbor = target.add(direction)
        if not env.in_bounds(neighbor.x, neighbor.y):
            continue
        state = env.tile(neighbor.x, neighbor.y)
        if env.is_unknown(neighbor.x, neighbor.y):
            unknown_neighbors += 1
        elif state == ORE_TITANIUM:
            ore_neighbors += 1

    width_mid = env.width // 2
    height_mid = env.height // 2
    quadrant_bonus = 0
    if (target.x < width_mid) != (self.core_pos.x < width_mid):
        quadrant_bonus += 1
    if (target.y < height_mid) != (self.core_pos.y < height_mid):
        quadrant_bonus += 1

    return (unknown_neighbors * 80 + ore_neighbors * 50 + quadrant_bonus * 30) - distance


def _pick_frontier_target(self: Harvester, pos: Position) -> Position | None:
    """Pick the best frontier tile to continue exploration"""
    env = self.environment_map
    if env is None:
        return None

    # Coarse scan keeps SEEK target picking cheap on large maps.
    stride = 2
    phase = self.edge_cycle_index % stride
    self.edge_cycle_index += 1
    best_target = None
    best_score = float("-inf")
    _ensure_seek_blacklists(self)
    blocked = self.blacklisted_seek_targets

    # Frontier tiles are known-passable tiles bordering unseen space.
    for y in range(phase, env.height, stride):
        for x in range(phase, env.width, stride):
            if (x, y) in blocked:
                continue
            if not _is_memory_passable(self, x, y):
                continue

            target = Position(x, y)
            for direction in DIRECTIONS_4:
                neighbor = target.add(direction)
                if not env.in_bounds(neighbor.x, neighbor.y):
                    continue
                if not env.is_unknown(neighbor.x, neighbor.y):
                    continue

                score = _frontier_score(self, pos, target)
                if score > best_score:
                    best_score = score
                    best_target = target
                break

    return best_target


def _fallback_edge_target(self: Harvester) -> Position:
    """Cycle through edge midpoints if no better exploration target exists"""
    env = self.environment_map
    if env is None:
        return self.current_pos.add(random_direction_4())
    w = env.width
    h = env.height
    targets = [
        Position(w // 2, 0),
        Position(w - 1, h // 2),
        Position(w // 2, h - 1),
        Position(0, h // 2),
    ]
    _ensure_seek_blacklists(self)
    for _ in range(len(targets)):
        target = targets[self.edge_cycle_index % len(targets)]
        self.edge_cycle_index += 1
        if (target.x, target.y) not in self.blacklisted_seek_targets:
            return target
    return targets[(self.edge_cycle_index - 1) % len(targets)]


def _pick_seek_target(self: Harvester, pos: Position) -> tuple[Position | None, bool]:
    """Choose between known titanium, predicted titanium, and frontier exploration."""
    env = self.environment_map
    if env is None:
        return pos.add(random_direction_4()), False

    _ensure_seek_blacklists(self)
    # Prefer confirmed titanium before symmetry guesses or generic exploration.
    blocked = set(self.blacklisted_ores) | set(self.blacklisted_seek_targets)
    while True:
        known_ti = env.nearest_known_titanium(pos, blocked, observed_only=True)
        if known_ti is None:
            break
        if _best_ore_approach(self, known_ti, pos) is not None:
            return known_ti, True
        key = (known_ti.x, known_ti.y)
        self.blacklisted_ores.add(key)
        blocked.add(key)

    if env.symmetry is not None:
        blocked = set(self.blacklisted_ores) | set(self.blacklisted_seek_targets)
        while True:
            predicted_ti = env.nearest_predicted_titanium(pos, blocked)
            if predicted_ti is None:
                break
            if _best_ore_approach(self, predicted_ti, pos) is not None:
                return predicted_ti, True
            key = (predicted_ti.x, predicted_ti.y)
            self.blacklisted_ores.add(key)
            blocked.add(key)

    frontier = _pick_frontier_target(self, pos)
    if frontier is not None:
        return frontier, False

    return _fallback_edge_target(self), False


def _target_still_viable(self: Harvester, target: Position, is_ore_target: bool) -> bool:
    env = self.environment_map
    if env is None:
        return False
    if not env.in_bounds(target.x, target.y):
        return False
    if is_ore_target:
        return env.tile(target.x, target.y) == ORE_TITANIUM
    # Frontier exploration targets expire once reached or once fully revealed.
    if target == self.current_pos:
        return False
    for direction in DIRECTIONS_4:
        neighbor = target.add(direction)
        if env.in_bounds(neighbor.x, neighbor.y) and env.is_unknown(neighbor.x, neighbor.y):
            return True
    return False


def _can_execute_seek_step(self: Harvester, c: Controller, move_dir: Direction) -> bool:
    next_pos = self.current_pos.add(move_dir)
    return c.can_move(move_dir) or (
        0 <= next_pos.x < c.get_map_width()
        and 0 <= next_pos.y < c.get_map_height()
        and c.get_tile_env(next_pos) == Environment.EMPTY
        and c.can_build_road(next_pos)
    )


def _seek_direction(self: Harvester, c: Controller, move_target: Position) -> Direction | None:
    w = c.get_map_width()
    h = c.get_map_height()
    if w <= 0 or h <= 0:
        return None

    # Guard D* goal construction against out-of-bounds exploration targets.
    if not (0 <= move_target.x < w and 0 <= move_target.y < h):
        move_target = Position(
            min(max(move_target.x, 0), w - 1),
            min(max(move_target.y, 0), h - 1),
        )

    if self.environment_map is not None:
        goal = (move_target.x, move_target.y)
        planner = self.seek_planner

        if planner is None or self.seek_planner_goal != goal:
            planner = DStarLite(self.environment_map, move_target.x, move_target.y, block_mask=_SEEK_BLOCK_MASK)
            self.seek_planner = planner
            self.seek_planner_goal = goal

        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner.set_dynamic_blockers(_seek_dynamic_blockers(self, c, move_target))
        planner.notify_map_changes()

        move_dir = planner.step()
        if (
            move_dir is not None
            and move_dir != Direction.CENTRE
            and _can_execute_seek_step(self, c, move_dir)
        ):
            return move_dir

    return None


def _seek(self: Harvester, c: Controller):
    """Explore, target titanium, and place harvesters when adjacent"""
    self._update_foundry_flag(c)
    _ensure_seek_blacklists(self)

    if self._try_build_harvester(c):
        self.state = type(self.state).RETURN
        return

    if self.target_pos is None or not _target_still_viable(self, self.target_pos, self.seek_target_is_ore):
        self.target_pos, self.seek_target_is_ore = _pick_seek_target(self, self.current_pos)
        if self.target_pos is None:
            return

    move_target = self.target_pos
    is_ore_target = self.seek_target_is_ore
    if is_ore_target:
        # Drop ores that are already claimed when they come into vision.
        if c.is_in_vision(self.target_pos) and not self._is_valid_titanium_target(c, self.target_pos):
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
            return

        # Move to an adjacent build tile, not onto the ore itself.
        move_target = _best_ore_approach(self, self.target_pos, c=c)
        if move_target is None:
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
            return
    elif move_target == self.current_pos:
        # Reached a non-ore exploration waypoint; pick a fresh frontier target.
        self.target_pos = None
        self.seek_target_is_ore = False
        return

    move_dir = _seek_direction(self, c, move_target)
    if move_dir is None:
        # Blacklist tiles that repeatedly prove unreachable for D*.
        key = (move_target.x, move_target.y)
        misses = self.seek_unreachable_counts.get(key, 0) + 1
        self.seek_unreachable_counts[key] = misses
        miss_limit = 5
        if not is_ore_target:
            miss_limit = 8
        if misses >= miss_limit:
            self.blacklisted_seek_targets.add(key)
            self.seek_unreachable_counts.pop(key, None)
            if is_ore_target:
                self.blacklisted_ores.add(key)
            self.target_pos = None
            self.seek_target_is_ore = False
        return

    self.seek_unreachable_counts.pop((move_target.x, move_target.y), None)
    self._advance(c, move_dir)
