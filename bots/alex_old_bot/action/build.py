from typing import Optional

from action.interface import Action, TaskResult
from world.sensing import can_afford
from cambc import Controller, Position, Direction, EntityType, Environment
import grid


def _is_adjacent(pos1: Position, pos2: Position) -> bool:
    return pos1.distance_squared(pos2) <= 2


def _can_and_should_destroy(
    c: Controller, position: Position, destroy: list[EntityType]
) -> bool:
    bid = c.get_tile_building_id(position)
    if bid is None:
        return False
    if c.get_team(bid) != c.get_team():
        return False
    return c.get_entity_type(bid) in destroy


# ---------------------------------------------------------------------------
# Directional sequence builders (conveyors, splitters)
# ---------------------------------------------------------------------------


class _BuildDirectionalSeq(Action):
    """Place a sequence of directional buildings in reverse order."""

    _entity_type: EntityType
    _default_destroy: list[EntityType]

    def __init__(
        self,
        positions: list[tuple[Position, Direction]],
        *,
        destroy: Optional[list[EntityType]] = None,
        wait_for_resources: Optional[tuple[int, int]] = None,
    ):
        super().__init__()
        positions.reverse()
        self.positions = positions
        self.destroy = destroy if destroy is not None else list(self._default_destroy)
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(
        cls, c: Controller, position: Position, direction: Direction
    ) -> bool:
        bid = c.get_tile_building_id(position)
        return (
            bid is not None
            and c.get_entity_type(bid) == cls._entity_type
            and c.get_direction(bid) == direction
        )

    def _build(self, c: Controller, pos: Position, direction: Direction) -> bool:
        raise NotImplementedError

    def can_run(self, c: Controller) -> bool:
        if not self.positions:
            return True
        next_pos, next_dir = self.positions[-1]
        if self._already_exists(c, next_pos, next_dir):
            return True
        has_action = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            self._entity_type,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )
        if self.wait_for_resources is not None and not has_resources:
            return False
        return has_resources and has_action

    def run(self, c: Controller) -> TaskResult:
        if not self.positions:
            return TaskResult.SUCCESS
        next_pos, next_dir = self.positions[-1]
        if not _is_adjacent(c.get_position(), next_pos):
            return TaskResult.FAILURE
        if self._already_exists(c, next_pos, next_dir):
            self.positions.pop()
            return TaskResult.SUCCESS
        if _can_and_should_destroy(c, next_pos, self.destroy) and can_afford(
            c, self._entity_type
        ):
            c.destroy(next_pos)
        if self._build(c, next_pos, next_dir):
            self.positions.pop()
            return TaskResult.SUCCESS if not self.positions else TaskResult.INCOMPLETE
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(positions={self.positions})"


class BuildConveyors(_BuildDirectionalSeq):
    _entity_type = EntityType.CONVEYOR
    _default_destroy = [EntityType.ROAD, EntityType.MARKER]

    def _build(self, c: Controller, pos: Position, direction: Direction) -> bool:
        if c.can_build_conveyor(pos, direction):
            c.build_conveyor(pos, direction)
            return True
        return False


class BuildSplitters(_BuildDirectionalSeq):
    _entity_type = EntityType.SPLITTER
    _default_destroy = [EntityType.ROAD, EntityType.MARKER, EntityType.CONVEYOR]

    def _build(self, c: Controller, pos: Position, direction: Direction) -> bool:
        if c.can_build_splitter(pos, direction):
            c.build_splitter(pos, direction)
            return True
        return False


# ---------------------------------------------------------------------------
# Single-placement builders (harvester, foundry)
# ---------------------------------------------------------------------------


class _BuildSingle(Action):
    """Place a single building on a target tile."""

    _entity_type: EntityType
    _default_destroy: list[EntityType]

    def __init__(
        self,
        position: Position,
        *,
        destroy: Optional[list[EntityType]] = None,
        wait_for_resources: Optional[tuple[int, int]] = None,
    ):
        super().__init__()
        self.position = position
        self.destroy = destroy if destroy is not None else list(self._default_destroy)
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        bid = c.get_tile_building_id(position)
        return bid is not None and c.get_entity_type(bid) == cls._entity_type

    def _build(self, c: Controller, position: Position) -> bool:
        raise NotImplementedError

    def can_run(self, c: Controller) -> bool:
        if self._already_exists(c, self.position):
            return True
        has_action = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            self._entity_type,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )
        if self.wait_for_resources is not None and not has_resources:
            return False
        return has_resources and has_action

    def run(self, c: Controller) -> TaskResult:
        if self._already_exists(c, self.position):
            return TaskResult.SUCCESS
        if not _is_adjacent(c.get_position(), self.position):
            return TaskResult.FAILURE
        if _can_and_should_destroy(c, self.position, self.destroy) and can_afford(
            c, self._entity_type
        ):
            c.destroy(self.position)
        if self._build(c, self.position):
            return TaskResult.SUCCESS
        return TaskResult.FAILURE


class BuildHarvester(_BuildSingle):
    _entity_type = EntityType.HARVESTER
    _default_destroy = [
        EntityType.ROAD,
        EntityType.MARKER,
        EntityType.BARRIER,
        EntityType.LAUNCHER,
    ]

    def _build(self, c: Controller, pos: Position) -> bool:
        if c.can_build_harvester(pos):
            c.build_harvester(pos)
            return True
        return False


class BuildFoundry(_BuildSingle):
    _entity_type = EntityType.FOUNDRY
    _default_destroy = [EntityType.ROAD, EntityType.MARKER]

    def __init__(
        self,
        position: Position,
        *,
        destroy: Optional[list[EntityType]] = None,
        wait_for_resources: Optional[tuple[int, int]] = (0, 0),
    ):
        super().__init__(
            position, destroy=destroy, wait_for_resources=wait_for_resources
        )

    def _build(self, c: Controller, pos: Position) -> bool:
        if c.can_build_foundry(pos):
            c.build_foundry(pos)
            return True
        return False


# ---------------------------------------------------------------------------
# Road (unique logic: passability checks, enemy road handling)
# ---------------------------------------------------------------------------


class BuildRoad(Action):
    passable = [
        EntityType.ROAD,
        EntityType.CONVEYOR,
        EntityType.BRIDGE,
        EntityType.SPLITTER,
    ]

    def __init__(
        self,
        position: Position,
        *,
        destroy: list[EntityType] = [],
        wait_for_resources: Optional[tuple[int, int]] = None,
        fail_on_enemy_road: bool = False,
        good_if_passable: bool = True,
    ):
        super().__init__()
        self.position = position
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources
        self.fail_on_enemy_road = fail_on_enemy_road
        self.good_if_passable = good_if_passable

        if self.good_if_passable and self.fail_on_enemy_road:
            raise ValueError(
                "Cannot have both good_if_passable and fail_on_enemy_road"
            )

    @classmethod
    def _already_exists_is_ours(
        cls, c: Controller, position: Position
    ) -> tuple[bool, bool]:
        bid = c.get_tile_building_id(position)
        if bid is None:
            return False, False
        return (c.get_entity_type(bid) == EntityType.ROAD), c.get_team(
            bid
        ) == c.get_team()

    def _is_passable_and_exists(self, c: Controller, position: Position) -> bool:
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
        has_action = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.ROAD,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )
        if self.wait_for_resources is not None and not has_resources:
            return False
        return has_resources and has_action

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


# ---------------------------------------------------------------------------
# Bridge (unique logic: target position)
# ---------------------------------------------------------------------------


class BuildBridge(Action):
    def __init__(
        self,
        position: Position,
        target: Position,
        *,
        destroy: list[EntityType] = [EntityType.ROAD, EntityType.MARKER],
        wait_for_resources: Optional[tuple[int, int]] = None,
    ):
        super().__init__()
        self.position = position
        self.target = target
        self.destroy = destroy
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(
        cls, c: Controller, position: Position, target: Position
    ) -> bool:
        bid = c.get_tile_building_id(position)
        return (
            bid is not None
            and c.get_entity_type(bid) == EntityType.BRIDGE
            and c.get_bridge_target(bid) == target
        )

    def can_run(self, c: Controller) -> bool:
        if self._already_exists(c, self.position, self.target):
            return True
        has_action = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            EntityType.BRIDGE,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )
        if self.wait_for_resources is not None and not has_resources:
            return False
        return has_resources and has_action

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

    def __str__(self) -> str:
        return f"BuildBridge: {self.position} -> {self.target}"


# ---------------------------------------------------------------------------
# Marker (unique logic: free, iterates positions)
# ---------------------------------------------------------------------------


class BuildMarker(Action):
    def __init__(
        self,
        message: int,
        *,
        destroy: list[EntityType] = [EntityType.MARKER, EntityType.ROAD],
        positions: Optional[list[Position]] = None,
    ):
        super().__init__()
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


# ---------------------------------------------------------------------------
# Simple sequence builders (barriers, launchers)
# ---------------------------------------------------------------------------


class _BuildSimpleSeq(Action):
    """Place a sequence of non-directional buildings."""

    _entity_type: EntityType
    _default_destroy: list[EntityType]

    def __init__(
        self,
        positions: list[Position],
        *,
        destroy: Optional[list[EntityType]] = None,
        wait_for_resources: Optional[tuple[int, int]] = (0, 0),
    ):
        super().__init__()
        self.positions = positions
        self.destroy = destroy if destroy is not None else list(self._default_destroy)
        self.wait_for_resources = wait_for_resources

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        raise NotImplementedError

    def _build(self, c: Controller, position: Position) -> bool:
        raise NotImplementedError

    def can_run(self, c: Controller) -> bool:
        if not self.positions:
            return True
        next_pos = self.positions[-1]
        if not c.is_in_vision(next_pos):
            return True  # let run() skip it
        if self._already_exists(c, next_pos):
            return True
        has_action = c.get_action_cooldown() == 0
        has_resources = can_afford(
            c,
            self._entity_type,
            ti_offset=self.wait_for_resources[0] if self.wait_for_resources else 0,
            ax_offset=self.wait_for_resources[1] if self.wait_for_resources else 0,
        )
        if self.wait_for_resources is not None and not has_resources:
            return False
        return has_resources and has_action

    def run(self, c: Controller) -> TaskResult:
        while self.positions:
            next_pos = self.positions[-1]
            if not c.is_in_vision(next_pos):
                self.positions.pop()
                continue

            if not _is_adjacent(c.get_position(), next_pos):
                return TaskResult.FAILURE

            if self._already_exists(c, next_pos):
                self.positions.pop()
                return TaskResult.SUCCESS

            if _can_and_should_destroy(
                c, next_pos, self.destroy
            ) and can_afford(c, self._entity_type):
                c.destroy(next_pos)

            if self._build(c, next_pos):
                self.positions.pop()
                return (
                    TaskResult.SUCCESS
                    if not self.positions
                    else TaskResult.INCOMPLETE
                )
            return TaskResult.FAILURE

        return TaskResult.SUCCESS

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(positions={self.positions})"


class BuildBarriers(_BuildSimpleSeq):
    _entity_type = EntityType.BARRIER
    _default_destroy = [EntityType.ROAD, EntityType.MARKER]

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        bid = c.get_tile_building_id(position)
        env = c.get_tile_env(position)
        return env == Environment.WALL or (
            bid is not None
            and c.get_entity_type(bid) in [EntityType.BARRIER, EntityType.CORE]
        )

    def _build(self, c: Controller, pos: Position) -> bool:
        if c.can_build_barrier(pos):
            c.build_barrier(pos)
            return True
        return False


class BuildLaunchers(_BuildSimpleSeq):
    _entity_type = EntityType.LAUNCHER
    _default_destroy = [EntityType.ROAD, EntityType.MARKER, EntityType.BARRIER]

    @classmethod
    def _already_exists(cls, c: Controller, position: Position) -> bool:
        bid = c.get_tile_building_id(position)
        env = c.get_tile_env(position)
        return env == Environment.WALL or (
            bid is not None
            and c.get_entity_type(bid) in [EntityType.BARRIER, EntityType.LAUNCHER]
        )

    def _build(self, c: Controller, pos: Position) -> bool:
        if c.can_build_launcher(pos):
            c.build_launcher(pos)
            return True
        return False
