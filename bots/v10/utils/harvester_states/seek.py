from cambc import Direction, Environment, Position

from utils.d_star import DStarLite
from utils.map_memory import CORE_OWN, ORE_AX, ORE_TI, TRAVERSABLE, UNKNOWN
from utils.movement import DIRECTIONS_4, _chebyshev, random_direction_4


def _is_memory_passable(self, x: int, y: int) -> bool:
    tile = self.memory._tiles[y][x]
    return tile in (TRAVERSABLE, ORE_AX, CORE_OWN)


def _best_ore_approach(
    self, ore_pos: Position, origin: Position | None = None
) -> Position | None:
    """Pick the best adjacent tile from which to build the harvester"""
    if origin is None:
        origin = self.current_pos

    best_target = None
    best_dist = float("inf")

    # Choose the closest viable cardinal build tile around the ore.
    for direction in DIRECTIONS_4:
        candidate = ore_pos.add(direction)
        if candidate == origin:
            return candidate

        if self.memory._tiles is not None:
            if not (0 <= candidate.x < self.memory._w and 0 <= candidate.y < self.memory._h):
                continue
            state = self.memory._tiles[candidate.y][candidate.x]
            if state not in (TRAVERSABLE, ORE_AX, CORE_OWN, UNKNOWN):
                continue

        dist = _chebyshev(origin, candidate)
        if dist < best_dist:
            best_dist = dist
            best_target = candidate

    return best_target


def _frontier_score(self, pos: Position, target: Position) -> float:
    """Score a frontier tile by exploration value and nearby ore density"""
    distance = pos.distance_squared(target) or 1
    unknown_neighbors = 0
    ore_neighbors = 0

    for direction in DIRECTIONS_4:
        neighbor = target.add(direction)
        if not (0 <= neighbor.x < self.memory._w and 0 <= neighbor.y < self.memory._h):
            continue
        state = self.memory._tiles[neighbor.y][neighbor.x]
        if state == UNKNOWN:
            unknown_neighbors += 1
        elif state == ORE_TI:
            ore_neighbors += 1

    width_mid = self.memory._w // 2
    height_mid = self.memory._h // 2
    quadrant_bonus = 0
    if (target.x < width_mid) != (self.core_pos.x < width_mid):
        quadrant_bonus += 1
    if (target.y < height_mid) != (self.core_pos.y < height_mid):
        quadrant_bonus += 1

    return (unknown_neighbors * 8 + ore_neighbors * 5 + quadrant_bonus * 3) - distance


def _pick_frontier_target(self, pos: Position) -> Position | None:
    """Pick the best frontier tile to continue exploration"""
    if self.memory._tiles is None:
        return None

    best_target = None
    best_score = float("-inf")

    # Frontier tiles are known-passable tiles bordering unseen space.
    for y in range(self.memory._h):
        for x in range(self.memory._w):
            if not _is_memory_passable(self, x, y):
                continue

            target = Position(x, y)
            for direction in DIRECTIONS_4:
                neighbor = target.add(direction)
                if not (0 <= neighbor.x < self.memory._w and 0 <= neighbor.y < self.memory._h):
                    continue
                if self.memory._tiles[neighbor.y][neighbor.x] != UNKNOWN:
                    continue

                score = _frontier_score(self, pos, target)
                if score > best_score:
                    best_score = score
                    best_target = target
                break

    return best_target


def _fallback_edge_target(self) -> Position:
    """Cycle through edge midpoints if no better exploration target exists"""
    w = self.memory._w
    h = self.memory._h
    targets = [
        Position(w // 2, 0),
        Position(w - 1, h // 2),
        Position(w // 2, h - 1),
        Position(0, h // 2),
    ]
    target = targets[self.edge_cycle_index % len(targets)]
    self.edge_cycle_index += 1
    return target


def _pick_seek_target(self, pos: Position) -> tuple[Position | None, bool]:
    """Choose between known titanium, predicted titanium, or frontier exploration"""
    # Prefer confirmed titanium before symmetry guesses or generic exploration.
    known_ti = self.memory.nearest_known_titanium(pos, self.blacklisted_ores)
    if known_ti is not None:
        return known_ti, True

    if self.memory.symmetry() is not None:
        predicted_ti = self.memory.nearest_predicted_titanium(pos)
        if predicted_ti is not None and (predicted_ti.x, predicted_ti.y) not in self.blacklisted_ores:
            return predicted_ti, True

    frontier = _pick_frontier_target(self, pos)
    if frontier is not None:
        return frontier, False

    if self.memory._tiles is None:
        return pos.add(random_direction_4()), False
    return _fallback_edge_target(self), False


def _can_execute_seek_step(self, c, move_dir: Direction) -> bool:
    next_pos = self.current_pos.add(move_dir)
    return c.can_move(move_dir) or (
        0 <= next_pos.x < c.get_map_width()
        and 0 <= next_pos.y < c.get_map_height()
        and c.get_tile_env(next_pos) == Environment.EMPTY
        and c.can_build_road(next_pos)
    )


def _seek_direction(self, c, move_target: Position) -> Direction | None:
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
            planner = DStarLite(self.environment_map, move_target.x, move_target.y)
            self.seek_planner = planner
            self.seek_planner_goal = goal

        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner.notify_map_changes()

        move_dir = planner.step()
        if (
            move_dir is not None
            and move_dir != Direction.CENTRE
            and _can_execute_seek_step(self, c, move_dir)
        ):
            return move_dir

    return None


def _seek(self, c):
    """Explore, target titanium, and place harvesters when adjacent"""
    self._update_foundry_flag(c)

    if self._try_build_harvester(c):
        self.state = type(self.state).RETURN
        return

    self.target_pos, is_ore_target = _pick_seek_target(self, self.current_pos)
    if self.target_pos is None:
        return

    move_target = self.target_pos
    if is_ore_target:
        # Drop ores that are already claimed when they come into vision.
        if c.is_in_vision(self.target_pos) and not self._is_valid_titanium_target(c, self.target_pos):
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            return

        # Move to an adjacent build tile, not onto the ore itself.
        move_target = _best_ore_approach(self, self.target_pos)
        if move_target is None:
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            return

    move_dir = _seek_direction(self, c, move_target)
    if move_dir is None:
        # No D* step this tick; hold and replan next tick with same target.
        return

    self._advance(c, move_dir)
