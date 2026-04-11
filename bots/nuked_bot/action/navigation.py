from action.interface import Action, TaskResult
from cambc import Controller, Direction, Position
from nav.d_star import DStarLite
from world.raw_map_representation import EnvironmentMap
import grid
from debugging import DEBUG_MODE


class Goto(Action):
    """Move a builder bot toward a target position.

    Plans a path each tick via D* Lite on the shared EnvironmentMap
    and advances one step per tick.

    Args:
        target: Destination position.
        wait_timer: Extra ticks tolerated while no path is available.
        timeout: Hard cap on total ticks before the action fails.
        env_map: Shared environment map used for planning.
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
        self._next_move: Direction | None = None
        self._planner: DStarLite | None = (
            DStarLite(env_map, target.x, target.y) if env_map is not None else None
        )

    def can_run(self, c: Controller) -> bool:
        if c.get_position() == self.target:
            return True

        self._next_move = self._plan_next_move(c)

        if c.get_move_cooldown() != 0:
            return False

        if self._next_move is None:
            return True

        step_pos = c.get_position().add(self._next_move)
        if self._needs_road(c, step_pos) and c.get_action_cooldown() != 0:
            return False

        return True

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

        direction = self._next_move
        self._next_move = None
        if not self._try_move(c, direction):
            return TaskResult.FAILURE

        self._waited = 0
        return TaskResult.INCOMPLETE

    def _plan_next_move(self, c: Controller) -> Direction | None:
        planner = self._planner
        if planner is None:
            return None

        pos = c.get_position()
        planner.set_position(pos.x, pos.y)
        planner.notify_map_changes()
        planner.plan()

        direction = planner.step()
        if DEBUG_MODE:
            if direction is None or direction == Direction.CENTRE:
                c.draw_indicator_line(pos, self.target, 255, 0, 0)
                return None

            c.draw_indicator_line(pos, self.target, 0, 255, 0)

        if DEBUG_MODE:
            for x1, y1, x2, y2 in planner.extract_path_lines():
                c.draw_indicator_line(Position(x1, y1), Position(x2, y2), 0, 0, 255)
        return direction

    def _try_move(self, c: Controller, direction: Direction) -> bool:
        new_pos = c.get_position().add(direction)
        if not grid.in_bounds(c, new_pos):
            return False

        if c.can_build_road(new_pos):
            c.build_road(new_pos)

        if not c.can_move(direction):
            return False

        c.move(direction)
        if self.env_map is not None:
            self.env_map.update(c)
        return True

    def _needs_road(self, c: Controller, pos: Position) -> bool:
        return c.get_tile_building_id(pos) is None

    def __str__(self) -> str:
        return f"Goto: {self.target}"
