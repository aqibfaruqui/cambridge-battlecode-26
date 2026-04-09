from typing import Optional
from collections import deque

from action.interface import Action, TaskResult
from cambc import Controller, Position, EntityType, Direction
from nav.alex_nav import AlexNav
from nav.space_map import build_space_map
import grid


class Goto(Action):
    """Move a builder bot toward one of several target positions.

    Plans a path each tick, builds roads and destroys friendly obstacles
    as needed, and advances one step at a time.

    Args:
        targets: Candidate destinations; the first reachable one is used.
        destroy: Friendly entity types the bot may tear down to clear the path.
        wait_timer: Max consecutive ticks to idle when no path is found.
        clear_roads_behind: If True, destroy the road on the tile the bot just left.
        timeout: Hard cap on total ticks before the action fails.
    """

    def __init__(
        self,
        targets: list[Position],
        *,
        destroy: list[EntityType] = [EntityType.MARKER, EntityType.BARRIER],
        wait_timer: int = 0,
        clear_roads_behind: bool = False,
        timeout: int = 200,
    ):
        super().__init__()
        self.targets = targets
        self.destroy = destroy
        self.wait_timer = wait_timer
        self.clear_roads_behind = clear_roads_behind
        self.timeout = timeout

        self.replace_wall_at: deque[Position] = deque()
        self._waited = 0
        self._elapsed = 0
        self._next_move: Optional[Direction] = None
        self.planner = AlexNav()

    def _is_owned_destroyable(self, c: Controller, pos: Position) -> bool:
        bid = c.get_tile_building_id(pos)
        return (
            bid is not None
            and c.get_team(bid) == c.get_team()
            and c.get_entity_type(bid) in self.destroy
        )

    def _needs_road(self, c: Controller, pos: Position) -> bool:
        bid = c.get_tile_building_id(pos)
        if bid is None:
            return True
        return (
            c.get_team(bid) == c.get_team() and c.get_entity_type(bid) in self.destroy
        )

    def _plan_next_move(self, c: Controller) -> Optional[Direction]:
        space_map = build_space_map(c, destroy=self.destroy)
        for target in self.targets:
            next_move, err = self.planner.plan(c.get_position(), target, space_map)
            if next_move is not None and err is None:
                return next_move
        return None

    def can_run(self, c: Controller) -> bool:
        if c.get_position() in self.targets:
            return True

        if (
            len(self.replace_wall_at) > 0
            and c.get_position() != self.replace_wall_at[0]
        ):
            return c.get_action_cooldown() == 0

        self._next_move = self._plan_next_move(c)

        if c.get_move_cooldown() != 0:
            return False

        if self._next_move is None:
            return True

        new_pos = c.get_position().add(self._next_move)
        if self._needs_road(c, new_pos) and c.get_action_cooldown() != 0:
            return False

        return True

    def _try_move(self, c: Controller, direction: Direction) -> TaskResult:
        old_pos = c.get_position()
        new_pos = old_pos.add(direction)

        if not grid.is_valid(c, new_pos) or not c.is_in_vision(new_pos):
            return TaskResult.FAILURE

        is_barrier = (
            c.get_tile_building_id(new_pos) is not None
            and c.get_entity_type(c.get_tile_building_id(new_pos))
            == EntityType.BARRIER
        )

        if not c.can_move(direction) and self._is_owned_destroyable(c, new_pos):
            c.destroy(new_pos)
            if is_barrier:
                self.replace_wall_at.append(new_pos)

        if c.can_build_road(new_pos):
            c.build_road(new_pos)

        if c.can_move(direction):
            c.move(direction)
            if (
                self.clear_roads_behind
                and c.can_destroy(old_pos)
                and c.get_entity_type(c.get_tile_building_id(old_pos))
                == EntityType.ROAD
            ):
                c.destroy(old_pos)
            return TaskResult.SUCCESS

        return TaskResult.FAILURE

    def run(self, c: Controller) -> TaskResult:
        self._elapsed += 1

        if c.get_position() in self.targets:
            return TaskResult.SUCCESS

        if self._elapsed > self.timeout:
            return TaskResult.FAILURE

        if self._waited > self.wait_timer:
            return TaskResult.FAILURE

        if (
            len(self.replace_wall_at) > 0
            and c.get_position() != self.replace_wall_at[0]
        ):
            wall_at = self.replace_wall_at.popleft()
            bid = c.get_tile_building_id(wall_at)
            if (
                bid is not None
                and c.get_team(bid) == c.get_team()
                and c.get_entity_type(bid) == EntityType.ROAD
                and c.can_destroy(wall_at)
            ):
                c.destroy(wall_at)
            if c.can_build_barrier(wall_at):
                c.build_barrier(wall_at)
                return TaskResult.INCOMPLETE
            else:
                return TaskResult.SUCCESS

        if self._next_move is None:
            self._waited += 1
            return TaskResult.INCOMPLETE

        result = self._try_move(c, self._next_move)
        self._next_move = None

        if result == TaskResult.SUCCESS:
            return TaskResult.INCOMPLETE
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"Goto: {self.targets}"
