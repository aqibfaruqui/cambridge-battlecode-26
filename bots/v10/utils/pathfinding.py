from collections import deque

from cambc import Controller, Direction, EntityType, Environment, Position
from utils.board import is_wall
from utils.movement import (
    DIRECTIONS_4,
    _manhattan,
    bug_nav,
    on_map,
    reached_core,
)
from utils.map_memory import UNKNOWN, WALL, TRAVERSABLE, ORE_TI, ORE_AX, CORE_OWN, CORE_ENEMY, MapMemory

_WALKABLE_BUILDINGS = frozenset(
    {EntityType.ROAD, EntityType.CONVEYOR, EntityType.BRIDGE}
)
_STUCK_RESET_TURNS = 2
_RETURN_BFS_WORK = 96
_RETURN_BFS_DIRECTION_WORK = 192

# Tiles that block movement in BFS.
_BFS_BLOCKED = frozenset({WALL, ORE_TI, CORE_ENEMY})


def _is_bfs_passable(tile: int) -> bool:
    """BFS passability: only confirmed traversable tiles.
    UNKNOWN is NOT passable — conservative routing avoids planning through
    walls we haven't seen yet. Symmetry projection fills in the map quickly
    so the BFS graph still covers far more than v9's plain observation.
    CORE_OWN is passable (our builders walk through it).
    """
    return tile in (TRAVERSABLE, ORE_AX, CORE_OWN)


class Pathfinding:
    def __init__(self):
        self._follow_state: dict | None = None
        self._memory: MapMemory | None = None
        self._map_version: int = -1
        self._reverse_bfs_cache: dict[tuple[str, int, int], dict] = {}
        self._return_bfs_cache: dict | None = None
        self._return_bfs_build: dict | None = None
        self._last_position: tuple[int, int] | None = None
        self._stuck_turns: int = 0

    def set_memory(self, memory) -> None:
        self._memory = memory

    def reset(self):
        self._follow_state = None
        self._last_position = None
        self._stuck_turns = 0

    def reset_return_bfs(self) -> None:
        self._return_bfs_cache = None
        self._return_bfs_build = None

    def next_direction(
        self, c: Controller, current: Position, target: Position
    ) -> Direction | None:
        if current == target:
            self.reset()
            return None

        self._refresh_progress(current)

        forward = current.direction_to(target)
        if _can_progress(c, current, forward):
            self._follow_state = None
            return forward

        direction, self._follow_state = bug_nav(
            c, current, target, self._follow_state
        )
        return direction

    def harvester_direction(
        self, c: Controller, current: Position, target: Position
    ) -> Direction | None:
        if _is_cardinal_adjacent(current, target):
            self.reset()
            return None

        self._refresh_progress(current)

        cache = self._ensure_reverse_bfs_harvester(c, current, target)
        if cache is not None:
            best_direction = None
            best_distance = float("inf")

            for direction in DIRECTIONS_4:
                if not _can_harvester_progress(c, current, direction):
                    continue

                next_pos = current.add(direction)
                next_distance = cache["distances"][next_pos.y][next_pos.x]
                if next_distance is None or next_distance >= best_distance:
                    continue

                best_distance = next_distance
                best_direction = direction

            if best_direction is not None:
                self._follow_state = None
                return best_direction

        fallback_target = self._fallback_harvester_goal(c, current, target)
        direction, self._follow_state = bug_nav(
            c, current, fallback_target, self._follow_state
        )
        return direction

    def reverse_bfs_direction_harvester(
        self, c: Controller, current: Position, target: Position
    ) -> Direction | None:
        return self.harvester_direction(c, current, target)

    def return_distances(self, c: Controller, core_pos: Position) -> dict:
        mem_version = self._memory.version if self._memory is not None else -1
        core_key = (core_pos.x, core_pos.y)
        cache = self._return_bfs_cache
        if (
            cache is not None
            and cache["version"] == mem_version
            and cache["core"] == core_key
        ):
            return cache

        build = self._return_bfs_build
        if (
            build is None
            or build["version"] != mem_version
            or build["core"] != core_key
        ):
            width = c.get_map_width()
            height = c.get_map_height()
            size = width * height
            distances = [-1] * size
            next_dir: list[Direction | None] = [None] * size
            queue = deque()
            append = queue.append
            core_x = core_pos.x
            core_y = core_pos.y

            for y in range(max(0, core_y - 1), min(height, core_y + 2)):
                row_offset = y * width
                for x in range(max(0, core_x - 1), min(width, core_x + 2)):
                    if not self._is_return_tile_passable_xy(c, x, y):
                        continue
                    idx = row_offset + x
                    distances[idx] = 0
                    append(idx)

            build = {
                "version": mem_version,
                "core": core_key,
                "width": width,
                "height": height,
                "distances": distances,
                "next_dir": next_dir,
                "queue": queue,
                "done": False,
            }
            self._return_bfs_build = build

        self._advance_return_bfs(c, build, _RETURN_BFS_WORK)
        if build["done"]:
            self._return_bfs_cache = build
            self._return_bfs_build = None
            return build

        return cache if cache is not None else build

    def return_direction(
        self,
        c: Controller,
        current: Position,
        distances: dict,
    ) -> Direction | None:
        x = current.x
        y = current.y
        width = distances["width"]
        height = distances["height"]
        if not (0 <= x < width and 0 <= y < height):
            return None
        idx = y * width + x
        direction = distances["next_dir"][idx]
        if direction is not None or distances.get("done", True):
            return direction

        self._advance_return_bfs(c, distances, _RETURN_BFS_DIRECTION_WORK)
        return distances["next_dir"][idx]

    def _refresh_progress(self, current: Position):
        current_key = (current.x, current.y)
        if self._last_position == current_key:
            self._stuck_turns += 1
        else:
            self._last_position = current_key
            self._stuck_turns = 0

        if self._stuck_turns < _STUCK_RESET_TURNS:
            return

        self._follow_state = None
        self._stuck_turns = 0

    def _ensure_reverse_bfs_harvester(
        self, c: Controller, current: Position, target: Position
    ) -> dict | None:
        if self._memory is None or self._memory._tiles is None:
            return None

        mem_version = self._memory.version
        target_key = ("harvester", target.x, target.y)
        cache = self._reverse_bfs_cache.get(target_key)
        if cache is not None and cache["version"] == mem_version:
            return cache

        goals = self._known_goal_positions_harvester(current, target)
        if not goals:
            self._reverse_bfs_cache.pop(target_key, None)
            return None

        distances = self._build_reverse_bfs_cardinal(c, goals)
        current_distance = distances[current.y][current.x]
        if current_distance is None and not _is_cardinal_adjacent(current, target):
            self._reverse_bfs_cache.pop(target_key, None)
            return None

        cache = {"version": mem_version, "distances": distances}
        self._reverse_bfs_cache[target_key] = cache
        return cache

    def _known_goal_positions_harvester(
        self, current: Position, target: Position
    ) -> list[Position]:
        if self._memory is None or self._memory._tiles is None:
            return []

        # If target is confirmed passable, route directly to it.
        if self._is_confirmed_passable(target):
            return [target]

        # Target is ore/wall/unknown — find confirmed-passable adjacent tiles.
        goals = []
        seen = set()
        for direction in DIRECTIONS_4:
            candidate = target.add(direction)
            key = (candidate.x, candidate.y)
            if key in seen:
                continue
            seen.add(key)
            if candidate == current or self._is_confirmed_passable(candidate):
                goals.append(candidate)
        return goals

    def _build_reverse_bfs_cardinal(
        self, c: Controller, goals: list[Position]
    ) -> list[list[int | None]]:
        assert self._memory is not None
        tiles = self._memory._tiles
        w = self._memory._w
        h = self._memory._h
        assert tiles is not None
        distances: list[list[int | None]] = [[None] * w for _ in range(h)]
        queue = deque()

        for goal in goals:
            distances[goal.y][goal.x] = 0
            queue.append((goal.x, goal.y))

        while queue:
            px, py = queue.popleft()
            next_dist = distances[py][px] + 1
            for nx, ny in ((px, py - 1), (px, py + 1), (px - 1, py), (px + 1, py)):
                if not (0 <= nx < w and 0 <= ny < h):
                    continue
                if not _is_bfs_passable(tiles[ny][nx]):
                    continue
                if distances[ny][nx] is not None:
                    continue
                distances[ny][nx] = next_dist
                queue.append((nx, ny))

        return distances

    def _is_confirmed_passable(self, pos: Position) -> bool:
        if self._memory is None or self._memory._tiles is None:
            return False
        if not (0 <= pos.x < self._memory._w and 0 <= pos.y < self._memory._h):
            return False
        return _is_bfs_passable(self._memory._tiles[pos.y][pos.x])

    def _fallback_harvester_goal(
        self, c: Controller, current: Position, target: Position
    ) -> Position:
        best_goal = target
        best_score = float("inf")

        for direction in DIRECTIONS_4:
            candidate = target.add(direction)
            if candidate == current:
                return candidate
            if not on_map(c, candidate):
                continue

            if c.is_in_vision(candidate):
                if not _is_future_clearable(c, candidate):
                    continue
            elif not self._is_confirmed_passable(candidate):
                continue

            score = _manhattan(current, candidate)
            if score < best_score:
                best_score = score
                best_goal = candidate

        return best_goal

    def _is_return_tile_passable(self, c: Controller, pos: Position) -> bool:
        return self._is_return_tile_passable_xy(c, pos.x, pos.y)

    def _is_return_tile_passable_xy(self, c: Controller, x: int, y: int) -> bool:
        if self._memory is None or self._memory._tiles is None:
            return False

        state = self._memory._tiles[y][x]
        return state in (TRAVERSABLE, CORE_OWN, UNKNOWN)

    def _advance_return_bfs(self, c: Controller, build: dict, work: int) -> None:
        if build["done"]:
            return

        width = build["width"]
        height = build["height"]
        distances = build["distances"]
        next_dir = build["next_dir"]
        queue = build["queue"]
        popleft = queue.popleft
        append = queue.append
        is_passable = self._is_return_tile_passable_xy

        while queue and work > 0:
            work -= 1
            idx = popleft()
            px = idx % width
            py = idx // width
            next_dist = distances[idx] + 1

            if py > 0:
                nidx = idx - width
                if distances[nidx] == -1 and is_passable(c, px, py - 1):
                    distances[nidx] = next_dist
                    next_dir[nidx] = Direction.SOUTH
                    append(nidx)

            if px + 1 < width:
                nidx = idx + 1
                if distances[nidx] == -1 and is_passable(c, px + 1, py):
                    distances[nidx] = next_dist
                    next_dir[nidx] = Direction.WEST
                    append(nidx)

            if py + 1 < height:
                nidx = idx + width
                if distances[nidx] == -1 and is_passable(c, px, py + 1):
                    distances[nidx] = next_dist
                    next_dir[nidx] = Direction.NORTH
                    append(nidx)

            if px > 0:
                nidx = idx - 1
                if distances[nidx] == -1 and is_passable(c, px - 1, py):
                    distances[nidx] = next_dist
                    next_dir[nidx] = Direction.EAST
                    append(nidx)

        if not queue:
            build["done"] = True


def _is_cardinal_adjacent(a: Position, b: Position) -> bool:
    return abs(a.x - b.x) + abs(a.y - b.y) == 1


def _is_future_clearable(c: Controller, pos: Position) -> bool:
    if not on_map(c, pos):
        return False
    if is_wall(c, pos):
        return False

    building_id = c.get_tile_building_id(pos)
    if building_id is None:
        return c.get_tile_env(pos) == Environment.EMPTY

    entity_type = c.get_entity_type(building_id)
    if entity_type in _WALKABLE_BUILDINGS:
        return True

    return entity_type == EntityType.CORE and c.get_team(building_id) == c.get_team()


def _can_clear_and_step(c: Controller, current: Position, next_pos: Position) -> bool:
    if not on_map(c, next_pos):
        return False
    if is_wall(c, next_pos):
        return False

    direction = current.direction_to(next_pos)
    building_id = c.get_tile_building_id(next_pos)
    if building_id is None:
        if c.get_tile_env(next_pos) != Environment.EMPTY:
            return False
        if direction in DIRECTIONS_4:
            return c.can_build_conveyor(next_pos, direction.opposite())
        return c.can_build_road(next_pos)

    entity_type = c.get_entity_type(building_id)
    if entity_type in _WALKABLE_BUILDINGS:
        if c.can_move(direction):
            return True
        if entity_type == EntityType.ROAD and direction in DIRECTIONS_4:
            return _can_replace_road_with_conveyor(c, next_pos)
        return False

    return entity_type == EntityType.CORE and c.can_move(direction)


def _can_progress(c: Controller, current: Position, direction: Direction):
    next_pos = current.add(direction)
    return c.can_move(direction) or _can_clear_and_step(c, current, next_pos)


def _can_harvester_progress(c: Controller, current: Position, direction: Direction):
    if direction not in DIRECTIONS_4:
        return False

    next_pos = current.add(direction)
    if c.can_move(direction):
        return True

    if not on_map(c, next_pos):
        return False
    if c.get_tile_env(next_pos) != Environment.EMPTY:
        return False

    building_id = c.get_tile_building_id(next_pos)
    if building_id is not None:
        return (
            c.get_entity_type(building_id) == EntityType.ROAD
            and _can_replace_road_with_conveyor(c, next_pos)
        )

    return c.can_build_conveyor(next_pos, direction.opposite())


def _can_replace_road_with_conveyor(c: Controller, pos: Position) -> bool:
    if not c.can_destroy(pos):
        return False
    return c.get_global_resources()[0] >= c.get_conveyor_cost()[0]
