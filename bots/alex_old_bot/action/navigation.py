from enum import IntEnum
from typing import Optional
from collections import deque

from action.interface import Action, TaskResult
from world.state import GlobalState
from cambc import Controller, Position, EntityType, Direction
from nav.alex_nav import AlexNav
from nav.space_map import build_space_map
import grid


class NavigationMode(IntEnum):
    """Selects which path-planning backend to use."""

    ALEX_NAV = 0


class Goto(Action):
    """Move a builder bot toward one of several target positions.

    The action plans a path each tick, builds roads and destroys friendly
    obstacles (e.g. markers) as needed, and advances one step at a time.
    It reports INCOMPLETE while still en-route, SUCCESS on arrival, and
    FAILURE if the path is blocked beyond the wait budget or the timeout
    elapses.

    Args:
        global_state: Shared world state, updated after each successful move.
        targets: Candidate destinations; the first reachable one is used.
        destroy: Friendly entity types the bot may tear down to clear the path.
        mode: Path-planning backend.
        wait_timer: Max consecutive ticks to idle when no path is found before
            giving up.
        clear_roads_behind: If True, destroy the road on the tile the bot just
            left (useful for one-time corridors that should not persist).
        timeout: Hard cap on total ticks before the action fails.
    """

    replace_wall_at: deque[Position] = deque()

    def __init__(
        self,
        global_state: GlobalState,
        targets: list[Position],
        *,
        destroy: list[EntityType] = [EntityType.MARKER, EntityType.BARRIER],
        mode: NavigationMode = NavigationMode.ALEX_NAV,
        wait_timer: int = 0,
        clear_roads_behind: bool = False,
        timeout: int = 200,
    ):
        super().__init__()
        self.targets = targets
        self.global_state = global_state
        self.destroy = destroy
        self.mode = mode
        self.wait_timer = wait_timer
        self.clear_roads_behind = clear_roads_behind
        self.timeout = timeout

        self._waited = 0
        self._elapsed = 0
        self._next_move: Optional[Direction] = None
        match mode:
            case NavigationMode.ALEX_NAV:
                self.planner = AlexNav()
            case _:
                raise ValueError(f"Unknown navigation mode: {mode.name}")

    def _is_owned_destroyable(self, c: Controller, pos: Position) -> bool:
        """Return True if *pos* holds a friendly building whose type is in ``self.destroy``."""
        bid = c.get_tile_building_id(pos)
        return (
            bid is not None
            and c.get_team(bid) == c.get_team()
            and c.get_entity_type(bid) in self.destroy
        )

    def _needs_road(self, c: Controller, pos: Position) -> bool:
        """Return True if *pos* is empty or holds a friendly destroyable, meaning a road must be built."""
        bid = c.get_tile_building_id(pos)
        if bid is None:
            return True
        return (
            c.get_team(bid) == c.get_team() and c.get_entity_type(bid) in self.destroy
        )

    def _plan_next_move(self, c: Controller) -> Optional[Direction]:
        """Run the path planner against each target and return the first viable step, or None."""
        space_map = build_space_map(c, destroy=self.destroy)
        for target in self.targets:
            next_move, err = self.planner.plan(c.get_position(), target, space_map)
            if next_move is not None and err is None:
                return next_move
        return None

    def can_run(self, c: Controller) -> bool:
        """Pre-check: plan the next move and verify cooldowns allow acting this tick."""
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
            return True  # let run() handle wait/failure

        new_pos = c.get_position().add(self._next_move)
        if self._needs_road(c, new_pos) and c.get_action_cooldown() != 0:
            return False

        return True

    def _try_move(self, c: Controller, direction: Direction) -> TaskResult:
        """Attempt a single step: destroy obstacles, lay a road, and move. Optionally clean up the road behind."""
        old_pos = c.get_position()
        new_pos = old_pos.add(direction)

        if not grid.is_valid(c, new_pos) or not c.is_in_vision(new_pos):
            return TaskResult.FAILURE

        is_barrier = (
            c.get_tile_building_id(new_pos) is not None
            and c.get_entity_type(c.get_tile_building_id(new_pos)) == EntityType.BARRIER
        )

        if not c.can_move(direction) and self._is_owned_destroyable(c, new_pos):
            c.destroy(new_pos)
            if is_barrier:
                self.replace_wall_at.append(new_pos)

        if c.can_build_road(new_pos):
            c.build_road(new_pos)

        if c.can_move(direction):
            c.move(direction)
            self.global_state.update(c)
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
        """Execute one tick of navigation. Returns SUCCESS on arrival, INCOMPLETE while moving, or FAILURE."""
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
            ):
                c.destroy(wall_at)
            if c.can_build_barrier(wall_at):
                c.build_barrier(wall_at)
                return TaskResult.INCOMPLETE
            else:
                print(
                    f"couldnt rebuild on {wall_at}, passing because there's probably something useful there."
                )
                return TaskResult.SUCCESS

        if self._next_move is None:
            self._waited += 1
            return TaskResult.INCOMPLETE

        result = self._try_move(c, self._next_move)
        self._next_move = None

        if result == TaskResult.SUCCESS:
            return TaskResult.INCOMPLETE  # moved but not at target yet
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"Goto: {self.targets}"
