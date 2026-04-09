from typing import Optional

from action.interface import Action, TaskResult
from world.sensing import can_afford
from cambc import Controller, Position, Direction, EntityType, Environment
from world.state import GlobalState
import grid
from world.comms.for_builder_bot import BuilderBotMessages, BuilderBotMessageType


def _is_adjacent(pos1: Position, pos2: Position) -> bool:
    """Check whether two positions are adjacent (Chebyshev distance <= 1)."""
    return pos1.distance_squared(pos2) <= 2


def _find_nearby_position_claims(c: Controller) -> list[Position]:
    return [
        BuilderBotMessages.decode_claim_position(c.get_marker_value(bid))
        for bid in c.get_nearby_buildings()
        if c.get_entity_type(bid) == EntityType.MARKER
        and c.get_team(bid) == c.get_team()
        and BuilderBotMessages.is_builder_bot_message(c.get_marker_value(bid))
        and BuilderBotMessages.get_message_type(c.get_marker_value(bid))
        == BuilderBotMessageType.CLAIM_POSITION
    ]


def _can_and_should_destroy(
    c: Controller, position: Position, destroy: list[EntityType]
) -> bool:
    """Return ``True`` if *position* holds a friendly building whose type is in *destroy*.

    Used as a pre-step before placing a new building: if the tile is occupied
    by one of the expendable types we listed, we destroy it first to make room.
    """
    bid = c.get_tile_building_id(position)
    if bid is None:
        return False
    if c.get_team(bid) != c.get_team():
        return False
    return c.get_entity_type(bid) in destroy


class BuildConveyors(Action):
    """Place a sequence of conveyors, one per turn, in reverse order.

    The list is consumed from the back: the last element is built first so
    that callers can specify positions in logical (source→sink) order.

    Args:
        global_state: Shared game state.
        positions: ``(position, direction)`` pairs in source→sink order.
        destroy: Entity types to tear down if they occupy a target tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — if set, ``can_run``
            returns ``False`` while resources are below the threshold instead
            of trying another action.
    """

    def __init__(
        self,
        global_state: GlobalState,
        positions: list[tuple[Position, Direction]],
        *,
        destroy: list[EntityType] = [EntityType.ROAD, EntityType.MARKER],
        wait_for_resources: Optional[tuple[int, int]] = None,
    ):
        super().__init__()
        positions.reverse()
        self.global_state = global_state
        self.positions = positions
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(
        cls, c: Controller, position: Position, direction: Direction
    ) -> bool:
        """Return ``True`` if a conveyor with the correct direction already occupies *position*."""
        bid = c.get_tile_building_id(position)
        return (
            (bid is not None)
            and (c.get_entity_type(bid) == EntityType.CONVEYOR)
            and (c.get_direction(bid) == direction)
        )

    def can_run(self, c: Controller) -> bool:
        if not self.positions:
            return True

        next_pos, next_dir = self.positions[-1]
        if self._already_exists(c, next_pos, next_dir):
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.CONVEYOR,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if self.wait_for_resources is not None and not has_resources:
            return False

        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        next_pos, next_dir = self.positions[-1]
        if not _is_adjacent(c.get_position(), next_pos):
            print(f"BuildConveyors: not adjacent to {next_pos}")
            return TaskResult.FAILURE

        if self._already_exists(c, next_pos, next_dir):
            print(f"BuildConveyors: already exists at {next_pos}")
            self.positions.pop()
            return TaskResult.SUCCESS

        if _can_and_should_destroy(c, next_pos, self.destroy) and can_afford(
            c, EntityType.CONVEYOR
        ):
            c.destroy(next_pos)

        if c.can_build_conveyor(next_pos, next_dir):
            print(f"BuildConveyors: building conveyor at {next_pos}")
            c.build_conveyor(next_pos, next_dir)
            self.positions.pop()
            return TaskResult.SUCCESS if not self.positions else TaskResult.INCOMPLETE

        print(f"BuildConveyors: failed to build conveyor at {next_pos}")
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"BuildConveyors(positions={self.positions})"


class BuildSplitters(Action):
    """Place a sequence of splitters, one per turn, in reverse order.

    Behaves identically to :class:`BuildConveyors` but builds splitters.

    Args:
        global_state: Shared game state.
        positions: ``(position, direction)`` pairs in source→sink order.
        destroy: Entity types to tear down if they occupy a target tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — if set, ``can_run``
            returns ``False`` while resources are below the threshold.
    """

    def __init__(
        self,
        global_state: GlobalState,
        positions: list[tuple[Position, Direction]],
        *,
        destroy: list[EntityType] = [
            EntityType.ROAD,
            EntityType.MARKER,
            EntityType.CONVEYOR,
        ],
        wait_for_resources: Optional[tuple[int, int]] = None,
    ):
        super().__init__()
        positions.reverse()
        self.global_state = global_state
        self.positions = positions
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(
        cls, c: Controller, position: Position, direction: Direction
    ) -> bool:
        """Return ``True`` if a splitter with the correct direction already occupies *position*."""
        bid = c.get_tile_building_id(position)
        return (
            (bid is not None)
            and (c.get_entity_type(bid) == EntityType.SPLITTER)
            and (c.get_direction(bid) == direction)
        )

    def can_run(self, c: Controller) -> bool:
        if not self.positions:
            return True

        next_pos, next_dir = self.positions[-1]
        if self._already_exists(c, next_pos, next_dir):
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.SPLITTER,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if self.wait_for_resources is not None and not has_resources:
            return False

        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        next_pos, next_dir = self.positions[-1]
        if not _is_adjacent(c.get_position(), next_pos):
            print(f"BuildSplitters: not adjacent to {next_pos}")
            return TaskResult.FAILURE

        if self._already_exists(c, next_pos, next_dir):
            print(f"BuildSplitters: already exists at {next_pos}")
            self.positions.pop()
            return TaskResult.SUCCESS

        if _can_and_should_destroy(c, next_pos, self.destroy) and can_afford(
            c, EntityType.SPLITTER
        ):
            c.destroy(next_pos)

        if c.can_build_splitter(next_pos, next_dir):
            print(f"BuildSplitters: building splitter at {next_pos}")
            c.build_splitter(next_pos, next_dir)
            self.positions.pop()
            return TaskResult.SUCCESS if not self.positions else TaskResult.INCOMPLETE

        print(f"BuildSplitters: failed to build splitter at {next_pos}")
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"BuildSplitters(positions={self.positions})"


class BuildHarvester(Action):
    """Place a single harvester on an ore tile.

    Args:
        global_state: Shared game state.
        position: Target tile (must be adjacent when ``run`` is called).
        destroy: Entity types to tear down if they occupy the target tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — if set, ``can_run``
            returns ``False`` while resources are below the threshold.
    """

    def __init__(
        self,
        global_state: GlobalState,
        position: Position,
        *,
        destroy: list[EntityType] = [
            EntityType.ROAD,
            EntityType.MARKER,
            EntityType.BARRIER,
            EntityType.LAUNCHER,
        ],
        wait_for_resources: Optional[tuple[int, int]] = None,
    ):
        super().__init__()
        self.position = position
        self.global_state = global_state
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        """Return ``True`` if a harvester already occupies *position*."""
        bid = c.get_tile_building_id(position)
        return (bid is not None) and (c.get_entity_type(bid) == EntityType.HARVESTER)

    def can_run(self, c: Controller) -> bool:
        if self._already_exists(c, self.position):
            print("BuildHarvester: already exists")
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.HARVESTER,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if (self.wait_for_resources is not None) and not has_resources:
            print("BuildHarvester: not enough resources but waiting")
            return False

        print(
            f"BuildHarvester: has_resources={has_resources}, has_action_ready={has_action_ready}"
        )
        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        if self._already_exists(c, self.position):
            return TaskResult.SUCCESS

        if not _is_adjacent(c.get_position(), self.position):
            return TaskResult.FAILURE

        if _can_and_should_destroy(c, self.position, self.destroy) and can_afford(
            c, EntityType.HARVESTER
        ):
            c.destroy(self.position)

        if c.can_build_harvester(self.position):
            c.build_harvester(self.position)
            return TaskResult.SUCCESS

        return TaskResult.FAILURE


class BuildFoundry(Action):
    """Place a single foundry (axionite refinery).

    Args:
        global_state: Shared game state.
        position: Target tile (must be adjacent when ``run`` is called).
        destroy: Entity types to tear down if they occupy the target tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — defaults to
            ``(0, 0)`` so the bot waits rather than skipping.
    """

    def __init__(
        self,
        global_state: GlobalState,
        position: Position,
        *,
        destroy: list[EntityType] = [EntityType.ROAD, EntityType.MARKER],
        wait_for_resources: Optional[tuple[int, int]] = (0, 0),
    ):
        super().__init__()
        self.position = position
        self.global_state = global_state
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        """Return ``True`` if a foundry already occupies *position*."""
        bid = c.get_tile_building_id(position)
        return (bid is not None) and (c.get_entity_type(bid) == EntityType.FOUNDRY)

    def can_run(self, c: Controller) -> bool:
        if self._already_exists(c, self.position):
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.FOUNDRY,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if (self.wait_for_resources is not None) and not has_resources:
            print("BuildFoundry: not enough resources but waiting")
            return False

        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        if self._already_exists(c, self.position):
            return TaskResult.SUCCESS

        if not _is_adjacent(c.get_position(), self.position):
            return TaskResult.FAILURE

        if _can_and_should_destroy(c, self.position, self.destroy) and can_afford(
            c, EntityType.FOUNDRY
        ):
            c.destroy(self.position)

        if c.can_build_foundry(self.position):
            c.build_foundry(self.position)
            return TaskResult.SUCCESS

        return TaskResult.FAILURE


class BuildRoad(Action):
    """Place a single road tile.

    Args:
        global_state: Shared game state.
        position: Target tile (must be adjacent when ``run`` is called).
        destroy: Entity types to tear down if they occupy the target tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — if set, ``can_run``
            returns ``False`` while resources are below the threshold.
        fail_on_enemy_road: If ``True``, ``run`` returns ``FAILURE`` when an
            enemy road already occupies the tile.
        good_if_passable: If ``True`` (default), any passable building
            (road, conveyor, bridge, splitter, or friendly core) counts as
            success — avoids tearing down useful infrastructure.

    Raises:
        ValueError: If both *fail_on_enemy_road* and *good_if_passable* are set.
    """

    def __init__(
        self,
        global_state: GlobalState,
        position: Position,
        *,
        destroy: list[EntityType] = [],
        wait_for_resources: Optional[tuple[int, int]] = None,
        fail_on_enemy_road: bool = False,
        good_if_passable: bool = True,
    ):
        super().__init__()
        self.global_state = global_state
        self.position = position
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources
        self.fail_on_enemy_road = fail_on_enemy_road
        self.good_if_passable = good_if_passable

        if self.good_if_passable and self.fail_on_enemy_road:
            raise ValueError(
                "Cannot have both good_if_passable and fail_on_enemy_road for a BuildRoad task"
            )

    passable = [
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.BRIDGE,
        EntityType.SPLITTER,
    ]

    @classmethod
    def _already_exists_is_ours(
        cls, c: Controller, position: Position
    ) -> tuple[bool, bool]:
        """Return ``(exists, is_ours)`` for a road at *position*."""
        bid = c.get_tile_building_id(position)
        if bid is None:
            return False, False
        return (
            (bid is not None) and (c.get_entity_type(bid) == EntityType.ROAD)
        ), c.get_team(bid) == c.get_team()

    def _is_passable_and_exists(self, c: Controller, position: Position) -> bool:
        """Return ``True`` if the tile holds a building the bot can walk through."""
        bid = c.get_tile_building_id(position)
        if bid is None:
            return False

        return c.get_entity_type(bid) in self.passable or (
            c.get_entity_type(bid) == EntityType.CORE
            and c.get_team(bid) == c.get_team()
        )

    def can_run(self, c: Controller) -> bool:
        if self.good_if_passable and self._is_passable_and_exists(c, self.position):
            return True

        exists, _ = self._already_exists_is_ours(c, self.position)
        if exists:
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.ROAD,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if self.wait_for_resources is not None and not has_resources:
            return False

        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        exists, ours = self._already_exists_is_ours(c, self.position)
        if exists and not self.fail_on_enemy_road:
            return TaskResult.SUCCESS
        elif exists and ours:
            return TaskResult.SUCCESS
        elif exists and not ours:
            return TaskResult.FAILURE

        if not _is_adjacent(c.get_position(), self.position):
            return TaskResult.FAILURE

        if self.good_if_passable and self._is_passable_and_exists(c, self.position):
            return TaskResult.SUCCESS

        if _can_and_should_destroy(c, self.position, self.destroy) and can_afford(
            c, EntityType.ROAD
        ):
            c.destroy(self.position)

        if c.can_build_road(self.position):
            c.build_road(self.position)
            return TaskResult.SUCCESS

        return TaskResult.FAILURE


class BuildBridge(Action):
    """Place a single bridge from *position* to *target*.

    Args:
        global_state: Shared game state.
        position: The tile the bridge occupies (must be adjacent to builder).
        target: The tile the bridge connects to.
        destroy: Entity types to tear down if they occupy the bridge tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — if set, ``can_run``
            returns ``False`` while resources are below the threshold.
    """

    def __init__(
        self,
        global_state: GlobalState,
        position: Position,
        target: Position,
        *,
        destroy: list[EntityType] = [EntityType.ROAD, EntityType.MARKER],
        wait_for_resources: Optional[tuple[int, int]] = None,
    ):
        super().__init__()
        self.global_state = global_state
        self.position = position
        self.target = target
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    def __str__(self) -> str:
        return f"BuildBridge: {self.position} -> {self.target}"

    @classmethod
    def _already_exists(
        cls, c: Controller, position: Position, target: Position
    ) -> bool:
        """Return ``True`` if a bridge at *position* already points to *target*."""
        bid = c.get_tile_building_id(position)
        return (
            (bid is not None)
            and (c.get_entity_type(bid) == EntityType.BRIDGE)
            and (c.get_bridge_target(bid) == target)
        )

    def can_run(self, c: Controller) -> bool:
        if self._already_exists(c, self.position, self.target):
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.BRIDGE,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if self.wait_for_resources is not None and not has_resources:
            return False

        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        if self._already_exists(c, self.position, self.target):
            return TaskResult.SUCCESS

        if not _is_adjacent(c.get_position(), self.position):
            return TaskResult.FAILURE

        if _can_and_should_destroy(c, self.position, self.destroy) and can_afford(
            c, EntityType.BRIDGE
        ):
            c.destroy(self.position)

        if c.can_build_bridge(self.position, self.target):
            c.build_bridge(self.position, self.target)
            return TaskResult.SUCCESS

        return TaskResult.FAILURE


class BuildMarker(Action):
    """Place a marker carrying *message* on the first available adjacent tile.

    Markers are free and don't cost action cooldown, so ``can_run`` always
    returns ``True``.

    Args:
        global_state: Shared game state.
        message: Unsigned 32-bit integer stored in the marker.
        destroy: Entity types to tear down to make room for the marker.
        positions: Explicit tile list. If ``None``, uses all tiles adjacent
            to the builder's current position.
    """

    def __init__(
        self,
        global_state: GlobalState,
        message: int,
        *,
        destroy: list[EntityType] = [EntityType.MARKER, EntityType.ROAD],
        positions: Optional[list[Position]] = None,
    ):
        super().__init__()
        self.global_state = global_state
        self.message = message
        self.destroy = destroy
        self.positions = positions

    def can_run(self, _: Controller) -> bool:
        return True

    def run(self, c: Controller) -> TaskResult:
        pos_list = self.positions
        if pos_list is None:
            pos_list = grid.adjacent_positions(c, c.get_position())

        for pos in pos_list:
            if _can_and_should_destroy(c, pos, self.destroy):
                c.destroy(pos)

            if c.can_place_marker(pos):
                c.place_marker(pos, self.message)
                return TaskResult.SUCCESS

        return TaskResult.FAILURE


class BuildBarriers(Action):
    """Place a sequence of barriers, one per turn.

    Positions where a wall, barrier, or core already exists are skipped.

    Args:
        global_state: Shared game state.
        positions: Target tiles consumed from the back.
        destroy: Entity types to tear down if they occupy a target tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — defaults to
            ``(0, 0)`` so the bot waits rather than skipping.
    """

    def __init__(
        self,
        global_state: GlobalState,
        positions: list[Position],
        *,
        destroy: list[EntityType] = [EntityType.ROAD, EntityType.MARKER],
        wait_for_resources: Optional[tuple[int, int]] = (0, 0),
    ):
        super().__init__()
        self.global_state = global_state
        self.positions = positions
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        """Return ``True`` if *position* is already blocked (wall, barrier, or core)."""
        bid = c.get_tile_building_id(position)
        env = c.get_tile_env(position)
        return env == Environment.WALL or (
            bid is not None
            and c.get_entity_type(bid) in [EntityType.BARRIER, EntityType.CORE]
        )

    def can_run(self, c: Controller) -> bool:
        if not self.positions:
            return True

        next_barrier = self.positions[-1]
        if next_barrier is None:
            return self.allow_null
        if not c.is_in_vision(next_barrier):
            self.positions.pop()
            return self.can_run(c)
        if self._already_exists(c, next_barrier):
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.BARRIER,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if self.wait_for_resources is not None and not has_resources:
            return False

        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        if not self.positions:
            return TaskResult.SUCCESS
        next_barrier_pos = self.positions[-1]
        if not _is_adjacent(c.get_position(), next_barrier_pos):
            return TaskResult.FAILURE

        if self._already_exists(c, next_barrier_pos):
            self.positions.pop()
            return TaskResult.SUCCESS

        if _can_and_should_destroy(c, next_barrier_pos, self.destroy) and can_afford(
            c, EntityType.BARRIER
        ):
            c.destroy(next_barrier_pos)

        if c.can_build_barrier(next_barrier_pos):
            print(f"BuildBarriers: building barrier at {next_barrier_pos}")
            c.build_barrier(next_barrier_pos)
            self.positions.pop()
            return TaskResult.SUCCESS if not self.positions else TaskResult.INCOMPLETE

        print(f"BuildBarriers: failed to build barrier at {next_barrier_pos}")
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"BuildBarriers(positions={self.positions})"


class BuildLaunchers(Action):
    """Place a sequence of launchers, one per turn.

    Positions where a wall, barrier, or launcher already exists are skipped
    (launchers defend against enemy bots, so existing blockers are fine).

    Args:
        global_state: Shared game state.
        positions: Target tiles consumed from the back.
        destroy: Entity types to tear down if they occupy a target tile.
        wait_for_resources: ``(ti_reserve, ax_reserve)`` — defaults to
            ``(0, 0)`` so the bot waits rather than skipping.
    """

    def __init__(
        self,
        global_state: GlobalState,
        positions: list[Position],
        *,
        destroy: list[EntityType] = [
            EntityType.ROAD,
            EntityType.MARKER,
            EntityType.BARRIER,
        ],
        wait_for_resources: Optional[tuple[int, int]] = (0, 0),
    ):
        super().__init__()
        self.global_state = global_state
        self.positions = positions
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        """Return ``True`` if *position* is already defended (wall, barrier, or launcher)."""
        bid = c.get_tile_building_id(position)
        env = c.get_tile_env(position)
        return env == Environment.WALL or (
            bid is not None
            and c.get_entity_type(bid)
            in [
                EntityType.BARRIER,
                EntityType.LAUNCHER,
            ]
        )

    def can_run(self, c: Controller) -> bool:
        if not self.positions:
            return True

        next_launcher = self.positions[-1]
        if not c.is_in_vision(next_launcher):
            self.positions.pop()
            return self.can_run(c)
        if self._already_exists(c, next_launcher):
            return True

        has_action_ready = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.LAUNCHER,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )

        if self.wait_for_resources is not None and not has_resources:
            return False

        return has_resources and has_action_ready

    def run(self, c: Controller) -> TaskResult:
        if not self.positions:
            return TaskResult.FAILURE

        next_launcher_pos = self.positions[-1]
        if not _is_adjacent(c.get_position(), next_launcher_pos):
            print(f"BuildLaunchers: not adjacent to {next_launcher_pos}")
            return TaskResult.FAILURE

        if self._already_exists(c, next_launcher_pos):
            print(f"BuildLaunchers: already exists at {next_launcher_pos}")
            self.positions.pop()
            return TaskResult.SUCCESS

        if _can_and_should_destroy(c, next_launcher_pos, self.destroy) and can_afford(
            c, EntityType.LAUNCHER
        ):
            c.destroy(next_launcher_pos)

        if c.can_build_launcher(next_launcher_pos):
            print(f"BuildLaunchers: building launcher at {next_launcher_pos}")
            c.build_launcher(next_launcher_pos)
            self.positions.pop()
            return TaskResult.SUCCESS if not self.positions else TaskResult.INCOMPLETE

        print(f"BuildLaunchers: failed to build launcher at {next_launcher_pos}")
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"BuildLaunchers(positions={self.positions})"
