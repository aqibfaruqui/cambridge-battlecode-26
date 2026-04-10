from typing import Optional

from action.interface import Action, TaskResult, run_actions
from action.build import BuildBridge, BuildMarker
from action.navigation import Goto
from world.comms.for_builder_bot import BuilderBotMessages
from action.composed.join_nodes import (
    _find_bridge_landing,
    ACCEPTABLE_END_TYPES,
)
from nav.space_map import build_space_map
from cambc import Controller, Position, EntityType, ResourceType, Environment
from nav.alex_nav import AlexNav
import grid


class BridgeJoinNodes(Action):
    """Like JoinNodes, but only builds bridges and walls around each one."""

    interruptible = False

    def __init__(
        self,
        start_positions: list[Position],
        end_positions: list[Position],
        ore_type: ResourceType,
        *,
        wait_for_resources: Optional[tuple[int, int]] = (10, 0),
    ):
        super().__init__()
        self.start_positions = start_positions
        self.end_positions = end_positions
        self.ore_type = ore_type
        self.wait_for_resources = wait_for_resources

        self._current_positions: list[Position] = self.start_positions
        self._placed_nodes: list[tuple[Position, Position]] = []
        self._actions: list[Action] = []
        self._planner = AlexNav()

    def can_run(self, c: Controller) -> bool:
        return not self._actions or self._actions[-1].can_run(c)

    def _adjacent_to_any(self, c: Controller) -> Optional[Position]:
        candidates = [
            pos
            for pos in self._current_positions
            if grid.adjacent_to(c.get_position(), pos, can_be_on=True)
        ]
        for tile in candidates:
            bid = c.get_tile_building_id(tile)
            if (
                bid
                and c.get_team(bid) == c.get_team()
                and c.get_entity_type(bid) == EntityType.ROAD
            ):
                return tile
        return candidates[0] if candidates else None

    def _wallable_neighbors(self, c: Controller, pos: Position) -> list[Position]:
        result = []
        for adj in grid.adjacent_positions(c, pos):
            if not c.is_in_vision(adj):
                continue
            if c.get_tile_env(adj) == Environment.WALL:
                continue
            bid = c.get_tile_building_id(adj)
            if bid is not None:
                continue
            result.append(adj)
        return result

    def _append_bridge(
        self, _: Controller, from_pos: Position, to_pos: Position
    ) -> None:
        self._actions.append(Goto([to_pos], wait_timer=2))
        self._actions.append(
            BuildMarker(BuilderBotMessages.encode_claim_position(to_pos))
        )
        self._actions.append(
            BuildBridge(
                from_pos,
                to_pos,
                wait_for_resources=self.wait_for_resources,
                destroy=[EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER],
            )
        )
        self._placed_nodes.append((from_pos, to_pos))
        self._current_positions = [to_pos]

    def get_placed_nodes(self) -> list[tuple[Position, Position]]:
        return self._placed_nodes

    def run(self, c: Controller) -> TaskResult:
        result = run_actions(c, self._actions, skip_can_run=True)
        if result != TaskResult.SUCCESS:
            return result

        near = self._adjacent_to_any(c)
        _, best_end = self._closest_pair()

        if near is None:
            sorted_starts = sorted(
                self._current_positions, key=lambda p: p.distance_squared(best_end)
            )
            self._actions = [Goto(sorted_starts, wait_timer=2)]
            return TaskResult.INCOMPLETE

        if near in self.end_positions:
            return TaskResult.SUCCESS

        for d in grid.DIRS_CARDINAL:
            adj = near.add(d)
            if adj not in self.end_positions:
                continue
            bid = c.get_tile_building_id(adj)
            if bid is not None and c.get_entity_type(bid) in ACCEPTABLE_END_TYPES:
                self._append_bridge(c, near, adj)
                return TaskResult.INCOMPLETE

        for target in sorted(
            self.end_positions, key=lambda p: p.distance_squared(near)
        ):
            if near.distance_squared(target) <= 9:
                self._append_bridge(c, near, target)
                return TaskResult.INCOMPLETE

        space_map = build_space_map(
            c,
            allow_self=True,
            avoid_ore_adjacency=self.ore_type,
            passable_buildings=frozenset({EntityType.ROAD}),
            restrict_to_our_buildings=True,
        )
        for target in sorted(
            self.end_positions, key=lambda p: p.distance_squared(near)
        ):
            landing = _find_bridge_landing(space_map, c.get_position(), near, target)
            if landing is not None:
                self._append_bridge(c, near, landing)
                return TaskResult.INCOMPLETE

        if len(self._current_positions) > 1:
            self._current_positions = [p for p in self._current_positions if p != near]
            return TaskResult.INCOMPLETE

        return TaskResult.FAILURE

    def _closest_pair(self) -> tuple[Position, Position]:
        best_pair = None
        min_dist = float("inf")
        for s in self._current_positions:
            for e in self.end_positions:
                d = s.distance_squared(e)
                if d < min_dist:
                    min_dist = d
                    best_pair = (s, e)
        return best_pair

    def __str__(self) -> str:
        starts = self.start_positions[0:1]
        ends = self.end_positions[0:1]
        s_ellip = "..." if len(self.start_positions) > 1 else ""
        e_ellip = "..." if len(self.end_positions) > 1 else ""
        return f"BridgeJoinNodes({starts}{s_ellip}, {ends}{e_ellip})"
