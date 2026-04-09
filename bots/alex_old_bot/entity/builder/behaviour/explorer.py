from enum import IntEnum
from collections import deque
import random

from action.interface import Behaviour
from action.set_state import SetState
from action.composed.goto_place_harvester import GotoPlaceHarvester
from action.composed.join_nodes import JoinNodes
from action.composed.bridge_join_nodes import BridgeJoinNodes
from action.composed.wall_off_tile import WallOffTile

from action.navigation import Goto
from action.build import BuildBarriers
from world.state import GlobalState
from world.comms.for_builder_bot import BuilderBotMessages, BuilderBotMessageType
from world.comms.for_buildings import BuildingMessages
from cambc import Controller, Position, Environment, EntityType, Direction, ResourceType
import grid


class ExplorerState(IntEnum):
    TITANIUM = 0
    AXIONITE = 1
    TITANIUM_2 = 2
    AXIONITE_2 = 3


class Navigator(IntEnum):
    RANDOM = 0
    SPIRAL_FIRST = 1


def spiral_positions(
    cx: int, cy: int, w: int, h: int, gap: int = 4, skip: int = 4
) -> deque[Position]:
    """Generate outward spiral waypoints from (cx, cy) on a W×H grid.

    Rings at Chebyshev distance gap, 2*gap, 3*gap, ...
    Points sampled at every integer step along each ring's perimeter.
    Out-of-bounds points are skipped. Stops when a full ring is OOB.
    """
    result = deque()
    result.append(Position(cx, cy))
    ring = 1
    tile = 0
    while True:
        d = ring * gap
        points = []
        # Top edge: left to right at y = cy - d
        for x in range(cx - d, cx + d + 1):
            if tile % skip == 0:
                points.append(Position(x, cy - d))
            tile += 1
        # Right edge: top+1 to bottom at x = cx + d
        for y in range(cy - d + 1, cy + d + 1):
            if tile % skip == 0:
                points.append(Position(cx + d, y))
            tile += 1
        # Bottom edge: right-1 to left at y = cy + d
        for x in range(cx + d - 1, cx - d - 1, -1):
            if tile % skip == 0:
                points.append(Position(x, cy + d))
            tile += 1
        # Left edge: bottom-1 to top+1 at x = cx - d
        for y in range(cy + d - 1, cy - d, -1):
            if tile % skip == 0:
                points.append(Position(cx - d, y))
            tile += 1
        # Filter to in-bounds
        valid = [p for p in points if 0 <= p.x < w and 0 <= p.y < h]
        if not valid:
            break
        result.extend(valid)
        ring += 1
    return result


class Explorer(Behaviour):
    def __init__(self, navigator: Navigator):
        super().__init__()
        self.navigator = navigator
        self.global_state = GlobalState(
            track_core=True,
            track_enemy_core=True,
        )

        self._flag_self_core = True
        self._state = ExplorerState.TITANIUM
        self._placed_nodes: list[tuple[Position, Position | Direction]] = []
        self._axionite_ores: set[Position] = set()
        self._spiral = None

    def _next_location(self, c: Controller) -> Position:
        if self._spiral is None:
            self._spiral = spiral_positions(
                self.global_state.get_core_pos().x,
                self.global_state.get_core_pos().y,
                c.get_map_width(),
                c.get_map_height(),
            )
        match self.navigator:
            case Navigator.RANDOM:
                x = random.randint(0, c.get_map_width() - 1)
                y = random.randint(0, c.get_map_height() - 1)
                return Position(x, y)
            case Navigator.SPIRAL_FIRST:
                return self._spiral.popleft()
            case _:
                raise RuntimeError(f"Navigator {self.navigator.name} not implemented")

    def _find_nearby_environment(
        self, c: Controller, env: list[Environment]
    ) -> list[Position]:
        return [tile for tile in c.get_nearby_tiles() if c.get_tile_env(tile) in env]

    def _find_conveyor_to_intersect(self) -> tuple[Position, Direction]:
        conveyors = [
            (pos, nxt) for pos, nxt in self._placed_nodes if isinstance(nxt, Direction)
        ]
        if len(conveyors) < 2:
            raise RuntimeError("No conveyor to intersect")
        mid = len(conveyors) // 2
        return conveyors[mid][0], conveyors[mid - 1][1]

    def _find_nearby_markers(self, c: Controller) -> list[tuple[Position, int]]:
        return [
            (c.get_position(bid), c.get_marker_value(bid))
            for bid in c.get_nearby_buildings()
            if c.get_entity_type(bid) == EntityType.MARKER
            and c.get_team(bid) == c.get_team()
            and BuilderBotMessages.is_builder_bot_message(c.get_marker_value(bid))
        ]

    def _make_harvester_actions(
        self, c: Controller, candidate: Position
    ) -> tuple[SetState, BridgeJoinNodes, WallOffTile, GotoPlaceHarvester]:
        sorted_adjacent = sorted(
            grid.cardinally_adjacent_positions(c, candidate),
            key=lambda p: self.global_state.get_core_pos().distance_squared(p),
        )
        return (
            SetState(
                self,
                "_state",
                ExplorerState.AXIONITE
                if self._state == ExplorerState.TITANIUM
                else ExplorerState.AXIONITE_2,
            ),
            BridgeJoinNodes(
                self.global_state,
                sorted_adjacent,
                grid.adjacent_positions(c, self.global_state.get_core_pos()),
                ResourceType.TITANIUM,
            ),
            WallOffTile(self.global_state, candidate, use_launchers=False),
            GotoPlaceHarvester(self.global_state, c, candidate),
        )

    def _make_block_ore_actions(
        self, c: Controller, candidate: Position
    ) -> tuple[BuildBarriers, Goto]:
        return (
            BuildBarriers(self.global_state, [candidate]),
            Goto(self.global_state, grid.adjacent_positions(c, candidate)),
        )

    def _make_guard_bridge_actions(self, candidate: Position) -> WallOffTile:
        return WallOffTile(self.global_state, candidate)

    def _set_best_harvester_task(self, c: Controller, candidate: Position) -> None:
        pos = c.get_position()
        for i, task in enumerate(self.actions):
            if isinstance(task, GotoPlaceHarvester):
                if pos.distance_squared(candidate) < pos.distance_squared(task.target):
                    state, join, wall_off, goto = self._make_harvester_actions(
                        c, candidate
                    )
                    self.actions[i - 3] = state
                    self.actions[i - 2] = join
                    self.actions[i - 1] = wall_off
                    self.actions[i] = goto
                    self._placed_nodes = join.get_placed_nodes()
                return

        if any(isinstance(a, (JoinNodes, SetState, WallOffTile)) for a in self.actions):
            return

        state, join, wall_off, goto = self._make_harvester_actions(c, candidate)
        self.actions.extend([state, join, wall_off, goto])
        self._placed_nodes = join.get_placed_nodes()

    def _set_best_block_task(self, c: Controller, candidate: Position) -> None:
        pos = c.get_position()
        for i, task in enumerate(self.actions):
            if isinstance(task, Goto) and isinstance(
                self.actions[i - 1], BuildBarriers
            ):
                if pos.distance_squared(candidate) < pos.distance_squared(
                    task.targets[0]
                ):
                    build_barriers, goto = self._make_block_ore_actions(c, candidate)
                    self.actions[i - 1] = build_barriers
                    self.actions[i] = goto
                return

        if any(
            (isinstance(a, Goto) and isinstance(self.actions[i - 1], BuildBarriers))
            or isinstance(a, BuildBarriers)
            for i, a in enumerate(self.actions)
        ):
            return

        build_barriers, goto = self._make_block_ore_actions(c, candidate)
        self.actions.extend([build_barriers, goto])

    def _set_best_guard_task(self, candidate: Position) -> None:
        if any(isinstance(a, WallOffTile) for a in self.actions):
            return

        self.actions.append(self._make_guard_bridge_actions(candidate))

    def check_interrupts_block_ores(self, c: Controller) -> None:
        ores = sorted(
            (
                ore
                for ore in self._find_nearby_environment(c, [Environment.ORE_TITANIUM])
                if c.get_tile_building_id(ore) is None
            ),
            key=lambda p: c.get_position().distance_squared(p),
        )

        our_bridges = sorted(
            (
                c.get_position(bridge)
                for bridge in c.get_nearby_buildings()
                if c.get_team(bridge) == c.get_team()
                and c.get_entity_type(bridge) == EntityType.BRIDGE
                and any(
                    (
                        c.get_tile_building_id(tile) is None
                        and c.get_tile_env(tile) != Environment.WALL
                    )
                    or (
                        c.get_tile_building_id(tile) is not None
                        and c.get_entity_type(c.get_tile_building_id(tile))
                        in {EntityType.ROAD, EntityType.MARKER}
                        and c.get_team(c.get_tile_building_id(tile)) == c.get_team()
                    )
                    for tile in grid.cardinally_adjacent_positions(
                        c, c.get_position(bridge)
                    )
                    if c.is_in_vision(tile)
                )
            ),
            key=lambda p: c.get_position().distance_squared(p),
        )

        if our_bridges and not any(isinstance(a, WallOffTile) for a in self.actions):
            # Wall-off takes priority — remove any existing block task
            self.actions = [
                a
                for i, a in enumerate(self.actions)
                if not (
                    isinstance(a, BuildBarriers)
                    or (
                        isinstance(a, Goto)
                        and i > 0
                        and isinstance(self.actions[i - 1], BuildBarriers)
                    )
                )
            ]
            self._set_best_guard_task(our_bridges[0])
        elif ores and not any(isinstance(a, WallOffTile) for a in self.actions):
            self._set_best_block_task(c, ores[0])

    def check_interrupts(self, c: Controller) -> None:
        if c.get_current_round() > 20 and self._state == ExplorerState.AXIONITE:
            self._state = ExplorerState.TITANIUM_2

        if (
            self._state != ExplorerState.TITANIUM
            and self._state != ExplorerState.TITANIUM_2
        ):
            self.check_interrupts_block_ores(c)
            return

        self._axionite_ores.update(
            self._find_nearby_environment(c, [Environment.ORE_AXIONITE])
        )

        taken = {
            BuilderBotMessages.decode_claim_ore(msg)
            for _, msg in self._find_nearby_markers(c)
            if BuilderBotMessages.get_message_type(msg)
            == BuilderBotMessageType.CLAIM_ORE
        }

        ores = sorted(
            (
                ore
                for ore in self._find_nearby_environment(c, [Environment.ORE_TITANIUM])
                if ore not in taken
                and (
                    c.get_tile_building_id(ore) is None
                    or (
                        c.get_team(c.get_tile_building_id(ore)) == c.get_team()
                        and c.get_entity_type(c.get_tile_building_id(ore))
                        in [EntityType.BARRIER, EntityType.LAUNCHER]
                    )
                )
            ),
            key=lambda p: c.get_position().distance_squared(p),
        )

        if ores:
            self._set_best_harvester_task(c, ores[0])

    def check_transitions(self, c: Controller) -> None:
        pass

    def tick(self, c: Controller) -> None:
        self.global_state.update(c)
        super().tick(c)

        if self._flag_self_core:
            for tile in [
                tile for tile in c.get_nearby_tiles(2) if tile != c.get_position()
            ]:
                bid = c.get_tile_building_id(tile)
                if (
                    bid is not None
                    and c.get_team(bid) == c.get_team()
                    and c.get_entity_type(bid) == EntityType.ROAD
                ):
                    c.destroy(tile)

                if c.can_place_marker(tile):
                    c.place_marker(
                        tile,
                        BuildingMessages.encode_self_core_location(
                            self.global_state.get_core_pos()
                        ),
                    )
                    self._flag_self_core = False
                    return
        elif self.global_state.try_enemy_core_pos():
            for tile in [
                tile for tile in c.get_nearby_tiles(2) if tile != c.get_position()
            ]:
                bid = c.get_tile_building_id(tile)
                if (
                    bid is not None
                    and c.get_team(bid) == c.get_team()
                    and c.get_entity_type(bid) in [EntityType.ROAD, EntityType.MARKER]
                ):
                    c.destroy(tile)

                if c.can_place_marker(tile):
                    c.place_marker(
                        tile,
                        BuildingMessages.encode_enemy_core_location(
                            self.global_state.get_enemy_core_pos()
                        ),
                    )
                    self._flag_self_core = True
                    return

    def idle(self, c: Controller) -> None:
        if not self.actions:
            self.navigator = (
                Navigator.RANDOM
                if self._state == ExplorerState.AXIONITE_2
                else Navigator.SPIRAL_FIRST
            )
            ti, ax = c.get_global_resources()
            if ti < 300:
                return

            next_location = self._next_location(c)
            print(f"Idling explorer assigns next location {next_location}")
            self.actions.append(
                Goto(self.global_state, [next_location], clear_roads_behind=True)
            )
