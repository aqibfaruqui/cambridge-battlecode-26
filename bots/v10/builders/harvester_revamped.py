from enum import Enum

from cambc import Controller, Direction, EntityType, Environment, Position
from utils.board import is_ore_titanium
from utils.map_memory import CORE_OWN, ORE_TI, TRAVERSABLE, UNKNOWN, MapMemory
from utils.movement import (
    DIRECTIONS_4,
    _chebyshev,
    is_diagonal,
    random_direction_4,
    reached_core,
    split_diagonal,
)
from utils.pathfinding import Pathfinding


class HarvestState(Enum):
    __slots__ = ()

    SEEK = "seek"
    RETURN = "return"


class Harvester:
    def __init__(self, core_pos: Position):
        self.state = HarvestState.SEEK
        self.core_pos = core_pos
        self.current_pos = None

        self.ti = 0
        self.ax = 0
        self.cost_scale = 100.0
        self.titanium_found = False
        self.axionite_found = False
        self.foundry_prev_placed = False
        self.foundry_ready = False

        self.memory = MapMemory()
        self.memory.set_core(core_pos)
        self.pathfinder = Pathfinding()
        self.pathfinder.set_memory(self.memory)

        self.target_pos: Position | None = None
        self.blacklisted_ores: set[tuple[int, int]] = set()
        self.edge_cycle_index = 0
        self.harvester_pos: Position | None = None
        self.just_placed = False
        self.bridge_from: Position | None = None

    def _check_for_foundry(self, c: Controller):
        """Identify if another builder has built a foundry"""
        new_cost_scale = c.get_scale_percent()
        if new_cost_scale >= self.cost_scale + 100.0:
            self.foundry_prev_placed = True
        self.cost_scale = new_cost_scale

    def _can_trigger_foundry(self, c: Controller) -> bool:
        foundry_cost = c.get_foundry_cost()[0]
        return (
            self.titanium_found
            and self.axionite_found
            and self.ti >= foundry_cost
            and not self.foundry_prev_placed
        )

    def _update_foundry_flag(self, c: Controller):
        # Just a temporary flag to trigger the foundry, just to show its not implemented yet
        if self._can_trigger_foundry(c):
            self.foundry_ready = True

    def _clear_if_road(self, c: Controller, pos: Position):
        """Safely clear road tiles"""
        build_id = c.get_tile_building_id(pos)
        if (
            build_id is not None
            and c.get_entity_type(build_id) == EntityType.ROAD
            and c.can_destroy(pos)
        ):
            c.destroy(pos)

    def _advance(self, c: Controller, move_dir):
        """Move toward target and build a road on the tile stepped onto"""
        if move_dir is None:
            return

        move_pos = self.current_pos.add(move_dir)
        if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
            c.build_road(move_pos)

        if c.can_move(move_dir):
            c.move(move_dir)

    def _is_valid_titanium_target(self, c: Controller, ore_pos: Position) -> bool:
        if not is_ore_titanium(c, ore_pos):
            return False

        build_id = c.get_tile_building_id(ore_pos)
        if build_id is None:
            return True
        return c.get_entity_type(build_id) != EntityType.HARVESTER

    def _try_build_harvester(self, c: Controller) -> bool:
        """Check cardinal directions and place a titanium harvester"""
        for direction in DIRECTIONS_4:
            ore_pos = self.current_pos.add(direction)
            if not self._is_valid_titanium_target(c, ore_pos):
                continue

            self._clear_if_road(c, ore_pos)
            if not c.can_build_harvester(ore_pos):
                continue

            c.build_harvester(ore_pos)
            self.titanium_found = True
            self.blacklisted_ores.discard((ore_pos.x, ore_pos.y))
            self.target_pos = None
            self.harvester_pos = ore_pos
            self.just_placed = True
            self.bridge_from = None
            self.state = HarvestState.RETURN
            return True

        return False

    def _is_memory_passable(self, x: int, y: int) -> bool:
        tile = self.memory._tiles[y][x]
        return tile == TRAVERSABLE or tile == CORE_OWN

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
                if state not in (TRAVERSABLE, CORE_OWN, UNKNOWN):
                    continue

            dist = _chebyshev(origin, candidate)
            if dist < best_dist:
                best_dist = dist
                best_target = candidate

        return best_target

    # Frontier logic (we should change this tbh)

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
                if not self._is_memory_passable(x, y):
                    continue

                target = Position(x, y)
                for direction in DIRECTIONS_4:
                    neighbor = target.add(direction)
                    if not (0 <= neighbor.x < self.memory._w and 0 <= neighbor.y < self.memory._h):
                        continue
                    if self.memory._tiles[neighbor.y][neighbor.x] != UNKNOWN:
                        continue

                    score = self._frontier_score(pos, target)
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

        frontier = self._pick_frontier_target(pos)
        if frontier is not None:
            return frontier, False

        if self.memory._tiles is None:
            return pos.add(random_direction_4()), False
        return self._fallback_edge_target(), False

    # --- Return to Core ---

    def _build_first_connector(self, c: Controller) -> bool:
        """If builder has just placed harvester, build first connecting conveyor"""
        move_pos = self.current_pos

        # If the harvester was diagonal, pick one of the two cardinal join tiles.
        if self.harvester_pos and is_diagonal(self.current_pos, self.harvester_pos):
            ns, ew = split_diagonal(self.current_pos, self.harvester_pos)
            m1 = self.current_pos.add(ns)
            m2 = self.current_pos.add(ew)
            move_pos = (
                m1
                if m1.distance_squared(self.core_pos) < m2.distance_squared(self.core_pos)
                else m2
            )

        build_id = c.get_tile_building_id(move_pos)
        if build_id is not None and c.get_entity_type(build_id) == EntityType.ROAD and c.can_destroy(move_pos):
            c.destroy(move_pos)

        distances = self.pathfinder.return_distances(c, self.core_pos)
        move_n_plus_1 = self.pathfinder.return_direction(c, move_pos, distances)
        if move_n_plus_1 is None:
            conveyor_dir = move_pos.direction_to(self.core_pos)
        else:
            conveyor_dir = move_n_plus_1

        if c.can_build_conveyor(move_pos, conveyor_dir):
            c.build_conveyor(move_pos, conveyor_dir)

        if self.current_pos != move_pos:
            step_dir = self.current_pos.direction_to(move_pos)
            if c.can_move(step_dir):
                c.move(step_dir)
                return True
            return False

        return True

    def _build_return_step(self, c: Controller) -> bool:
        """Lay conveyor path back to core using return BFS"""
        distances = self.pathfinder.return_distances(c, self.core_pos)
        move_n = self.pathfinder.return_direction(c, self.current_pos, distances)
        if move_n is None:
            diagonal_dir = self.current_pos.direction_to(self.core_pos)
            if diagonal_dir in DIRECTIONS_4 or diagonal_dir == Direction.CENTRE:
                return False
            return self._handle_return_diagonal_step(c, diagonal_dir)

        pos_n = self.current_pos.add(move_n)
        move_n_plus_1 = self.pathfinder.return_direction(c, pos_n, distances)

        build_id = c.get_tile_building_id(pos_n)

        # Once the next step touches the core footprint, just walk in.
        if reached_core(pos_n, self.core_pos) and c.can_move(move_n):
            c.move(move_n)
            return True

        if build_id is not None and c.get_entity_type(build_id) == EntityType.CORE:
            if c.can_move(move_n):
                c.move(move_n)
                return True
            return False

        if move_n_plus_1 is None:
            conveyor_dir = pos_n.direction_to(self.core_pos)
        else:
            conveyor_dir = move_n_plus_1

        # Replace roads and wrong-way friendly conveyors before rebuilding.
        if build_id is not None:
            entity_type = c.get_entity_type(build_id)
            if entity_type == EntityType.ROAD and c.can_destroy(pos_n):
                c.destroy(pos_n)
            elif entity_type == EntityType.CONVEYOR:
                if c.get_team(build_id) != c.get_team():
                    return False
                if c.get_direction(build_id) != conveyor_dir and c.can_destroy(pos_n):
                    c.destroy(pos_n)
            elif c.get_team(build_id) != c.get_team():
                return False

        if c.get_tile_env(pos_n) == Environment.EMPTY and c.can_build_conveyor(pos_n, conveyor_dir):
            c.build_conveyor(pos_n, conveyor_dir)

        if c.can_move(move_n):
            c.move(move_n)
            return True

        return False

    def _handle_return_diagonal_step(self, c: Controller, move_dir: Direction) -> bool:
        """Move diagonally on road, then bridge that step next turn"""
        move_pos = self.current_pos.add(move_dir)

        if c.get_tile_env(move_pos) == Environment.EMPTY and c.can_build_road(move_pos):
            c.build_road(move_pos)

        if c.can_move(move_dir):
            self.bridge_from = self.current_pos
            c.move(move_dir)
            return True

        return False

    def _handle_pending_return_bridge(self, c: Controller) -> bool:
        """Replace the previous road with a bridge into the current tile"""
        if self.bridge_from is None:
            return False

        bridge_pos = self.bridge_from
        self.bridge_from = None

        build_id = c.get_tile_building_id(bridge_pos)
        if (
            build_id is not None
            and c.get_entity_type(build_id) == EntityType.ROAD
            and c.can_destroy(bridge_pos)
        ):
            c.destroy(bridge_pos)

        if c.can_build_bridge(bridge_pos, self.current_pos):
            c.build_bridge(bridge_pos, self.current_pos)
            return True

        return False

    def _seek(self, c: Controller):
        """Explore, target titanium, and place harvesters when adjacent"""
        self._update_foundry_flag(c)

        if self._try_build_harvester(c):
            self.state = HarvestState.RETURN
            return

        self.target_pos, is_ore_target = self._pick_seek_target(self.current_pos)
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
            move_target = self._best_ore_approach(self.target_pos)
            if move_target is None:
                self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
                self.target_pos = None
                return

        move_dir = self.pathfinder.next_direction(c, self.current_pos, move_target)
        if move_dir is None:
            self.target_pos = None
            return

        self._advance(c, move_dir)

    def _return(self, c: Controller):
        """Lay conveyors back to the core"""
        self._update_foundry_flag(c)

        if self.just_placed:
            if self._build_first_connector(c):
                self.just_placed = False
            return

        if reached_core(self.current_pos, self.core_pos):
            self.state = HarvestState.SEEK
            self.target_pos = None
            self.harvester_pos = None
            self.bridge_from = None
            return

        if self.bridge_from is not None:
            self._handle_pending_return_bridge(c)
            return

        self._build_return_step(c)

    def _draw_debug(self, c: Controller):
        """Draw state-based dot and target line for debugging"""
        state_colors = {
            HarvestState.SEEK: (0, 0, 255),
            HarvestState.RETURN: (255, 165, 0),
        }
        r, g, b = state_colors.get(self.state, (255, 255, 255))
        c.draw_indicator_dot(self.current_pos, r, g, b)

        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, r, g, b)
        elif self.state == HarvestState.RETURN and self.current_pos != self.core_pos:
            c.draw_indicator_line(self.current_pos, self.core_pos, 255, 255, 0)

    def run(self, c: Controller):
        self.current_pos = c.get_position()
        self.ti, self.ax = c.get_global_resources()
        self.memory.update(c)
        self._check_for_foundry(c)

        match self.state:
            case HarvestState.SEEK:
                self._seek(c)
            case HarvestState.RETURN:
                self._return(c)

        self._draw_debug(c)
