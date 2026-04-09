from typing import Optional

from world.state import GlobalState
from action.interface import Action, TaskResult, run_actions
from cambc import Controller, Position, EntityType, Direction, ResourceType
from action.build import BuildConveyors, BuildBridge
from action.navigation import Goto
from nav.space_map import (
    build_space_map,
    to_sm,
    sm_in_bounds,
    GotoTileRepresentation,
)
from nav.bfs import bfs_path
import grid

ACCEPTABLE_END_TYPES = {
    EntityType.GUNNER,
    EntityType.SENTINEL,
    EntityType.BREACH,
    EntityType.LAUNCHER,
    EntityType.FOUNDRY,
    EntityType.CORE,
}


def _find_bridge_landing(
    space_map: list[list[GotoTileRepresentation]],
    bot_pos: Position,
    from_pos: Position,
    toward_pos: Position,
) -> Optional[Position]:
    """Find the best passable tile within bridge range (r²<=9) closer to toward_pos."""
    best_landing = None
    best_dist = from_pos.distance_squared(toward_pos)
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx == 0 and dy == 0:
                continue
            land = Position(from_pos.x + dx, from_pos.y + dy)
            if from_pos.distance_squared(land) > 9:
                continue
            land_sm = to_sm(bot_pos, land)
            if not sm_in_bounds(land_sm):
                continue
            if space_map[land_sm[0]][land_sm[1]] != GotoTileRepresentation.CAN_MOVE:
                continue
            d = land.distance_squared(toward_pos)
            if d < best_dist:
                best_dist = d
                best_landing = land
    return best_landing


def _path_is_direct(path: list[Direction], start_sm: tuple[int, int]) -> bool:
    """True if the BFS path length is close to the manhattan distance (not winding)."""
    end_sm = start_sm
    for d in path:
        ddx, ddy = d.delta()
        end_sm = (end_sm[0] + ddx, end_sm[1] + ddy)
    manhattan = abs(end_sm[0] - start_sm[0]) + abs(end_sm[1] - start_sm[1])
    return manhattan == 0 or len(path) <= manhattan + 1


class JoinNodes(Action):
    def __init__(
        self,
        global_state: GlobalState,
        start_positions: list[Position],
        end_positions: list[Position],
        ore_type: ResourceType,
        *,
        wait_for_resources: Optional[tuple[int, int]] = (10, 0),
    ):
        super().__init__()
        self.global_state = global_state
        self.start_positions = start_positions
        self.end_positions = end_positions
        self.ore_type = ore_type
        self.wait_for_resources = wait_for_resources

        self._next_hop_start_positions: list[Position] = self.start_positions
        self._actions: list[Action] = []
        self._placed_nodes: list[tuple[Position, Position | Direction]] = []

    def __str__(self) -> str:
        starts = self.start_positions[0:1]
        ends = self.end_positions[0:1]
        s_ellip = "..." if len(self.start_positions) > 1 else ""
        e_ellip = "..." if len(self.end_positions) > 1 else ""
        return f"JoinNodes({starts}{s_ellip}, {ends}{e_ellip})"

    def can_run(self, c: Controller) -> bool:
        if not self._actions:
            return True
        return self._actions[-1].can_run(c)

    def _adjacent_to_any_start(self, c: Controller) -> Optional[Position]:
        candidates = []
        for pos in self._next_hop_start_positions:
            if grid.adjacent_to(c.get_position(), pos, can_be_on=True):
                candidates.append(pos)

        for tile in candidates:
            bid = c.get_tile_building_id(tile)
            if (
                bid is not None
                and c.get_team(bid) == c.get_team()
                and c.get_entity_type(bid) == EntityType.ROAD
            ):
                return tile

        return candidates[0] if candidates else None

    def _closest_pair(self) -> tuple[Position, Position]:
        best_pair = None
        min_dist = float("inf")
        for start_pos in self._next_hop_start_positions:
            for end_pos in self.end_positions:
                dist = start_pos.distance_squared(end_pos)
                if dist < min_dist:
                    min_dist = dist
                    best_pair = (start_pos, end_pos)
        return best_pair

    def _plan_next_link(
        self, c: Controller, from_pos: Position, toward_pos: Position
    ) -> Optional[tuple[Position, Position] | tuple[Position, Direction]]:
        space_map = build_space_map(
            c,
            allow_self=True,
            avoid_ore_adjacency=self.ore_type,
            passable_buildings=frozenset({EntityType.ROAD}),
        )
        start_sm = to_sm(c.get_position(), from_pos)
        target_sm = to_sm(c.get_position(), toward_pos)

        path = bfs_path(space_map, start_sm, target_sm, directions=grid.DIRS_CARDINAL)

        if not path:
            landing = _find_bridge_landing(
                space_map, c.get_position(), from_pos, toward_pos
            )
            return (from_pos, landing) if landing else None

        if _path_is_direct(path, start_sm):
            return from_pos, path[0]

        # Path is winding around obstacles — bridge to skip ahead
        landing = _find_bridge_landing(
            space_map, c.get_position(), from_pos, toward_pos
        )
        return (from_pos, landing) if landing else (from_pos, path[0])

    def _append_link(self, pos: Position, target: Position | Direction) -> None:
        if isinstance(target, Direction):
            self._actions.append(
                BuildConveyors(
                    self.global_state,
                    [(pos, target)],
                    wait_for_resources=self.wait_for_resources,
                )
            )
            self._placed_nodes.append((pos, target))
            self._next_hop_start_positions = [pos.add(target)]
        else:
            self._actions.append(
                BuildBridge(
                    self.global_state,
                    pos,
                    target,
                    wait_for_resources=self.wait_for_resources,
                )
            )
            self._placed_nodes.append((pos, target))
            self._next_hop_start_positions = [target]

    def run(self, c: Controller) -> TaskResult:
        result = run_actions(c, self._actions, skip_can_run=True)
        if result != TaskResult.SUCCESS:
            return result

        near_start = self._adjacent_to_any_start(c)
        best_start, best_end = self._closest_pair()

        if near_start is None:
            sorted_starting = sorted(
                self._next_hop_start_positions,
                key=lambda p: p.distance_squared(best_end),
            )
            self._actions = [Goto(self.global_state, sorted_starting)]
            return TaskResult.INCOMPLETE

        if near_start in self.end_positions:
            return TaskResult.SUCCESS

        # Adjacent to an acceptable end — build final conveyor
        for d in grid.DIRS_CARDINAL:
            adj = near_start.add(d)
            if adj not in self.end_positions:
                continue
            bid = c.get_tile_building_id(adj)
            if bid is not None and c.get_entity_type(bid) in ACCEPTABLE_END_TYPES:
                self._append_link(near_start, d)
                return TaskResult.INCOMPLETE

        # Plan next link toward the closest end position
        sorted_targets = sorted(
            self.end_positions,
            key=lambda p: p.distance_squared(best_start),
        )
        for target in sorted_targets:
            next_link = self._plan_next_link(c, near_start, target)
            if next_link is not None:
                self._append_link(*next_link)
                return TaskResult.INCOMPLETE

        return TaskResult.FAILURE

    def get_placed_nodes(self) -> list[tuple[Position, Position | Direction]]:
        return self._placed_nodes
