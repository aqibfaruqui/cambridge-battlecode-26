from world.raw_map_representation import EnvironmentMap
from typing import Optional

from action.interface import Action, TaskResult
from cambc import Controller, Position, Direction
from nav.d_star import DStarLite
import grid


class Goto(Action):
    """Move a builder bot toward a target position.

    Plans a path each tick via D* Lite on the shared EnvironmentMap
    and advances one step at a time.

    Args:
        target: Destination position.
        wait_timer: Max consecutive ticks to idle when no path is found.
        timeout: Hard cap on total ticks before the action fails.
    """

    def __init__(
        self,
        target: Position,
        *,
        wait_timer: int = 0,
        timeout: int = 200,
        env_map: EnvironmentMap | None = None,
    ):
        super().__init__()
        self.target = target
        self.wait_timer = wait_timer
        self.timeout = timeout
        self.env_map = env_map

        self._waited = 0
        self._elapsed = 0
        self._next_move: Optional[Direction] = None

        self._planner: DStarLite | None = None
        if env_map is not None:
            self._planner = DStarLite(env_map, target.x, target.y)

    def _needs_road(self, c: Controller, pos: Position) -> bool:
        return c.get_tile_building_id(pos) is None

    def _plan_next_move(self, c: Controller) -> Optional[Direction]:
        if self._planner is None:
            return None

        pos = c.get_position()
        self._planner.set_position(pos.x, pos.y)
        self._planner.notify_map_changes()
        self._planner.plan()
        direction = self._planner.step()

        if direction is not None:
            c.draw_indicator_line(pos, self.target, 0, 255, 0)
            lines = self._planner.extract_path_lines()
            for x1, y1, x2, y2 in lines:
                c.draw_indicator_line(Position(x1, y1), Position(x2, y2), 0, 0, 255)
            if direction == Direction.CENTRE:
                return None
            return direction

        c.draw_indicator_line(pos, self.target, 255, 0, 0)
        return None

    def can_run(self, c: Controller) -> bool:
        if c.get_position() == self.target:
            return True

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
        new_pos = c.get_position().add(direction)

        if not grid.in_bounds(c, new_pos):
            return TaskResult.FAILURE

        if c.can_build_road(new_pos):
            c.build_road(new_pos)

        if c.can_move(direction):
            c.move(direction)
            if self.env_map is not None:
                self.env_map.update(c)
            return TaskResult.SUCCESS

        return TaskResult.FAILURE

    def run(self, c: Controller) -> TaskResult:
        self._elapsed += 1

        if c.get_position() == self.target:
            return TaskResult.SUCCESS

        if self._elapsed > self.timeout:
            return TaskResult.FAILURE

        if self._waited > self.wait_timer:
            return TaskResult.FAILURE

        if self._next_move is None:
            self._waited += 1
            return TaskResult.INCOMPLETE

        result = self._try_move(c, self._next_move)
        self._next_move = None

        if result == TaskResult.SUCCESS:
            self._waited = 0
            return TaskResult.INCOMPLETE
        return TaskResult.FAILURE

    def __str__(self) -> str:
        return f"Goto: {self.target}"
