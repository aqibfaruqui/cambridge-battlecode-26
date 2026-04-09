from action.interface import Action, TaskResult, run_actions
from action.build import BuildBarriers, BuildLaunchers
from action.navigation import Goto
from cambc import Controller, Position, Environment, EntityType
from world.state import GlobalState
import grid


class WallOffTile(Action):
    def __init__(
        self, global_state: GlobalState, tile: Position, *, use_launchers=True
    ):
        super().__init__()
        self.global_state = global_state
        self.tile = tile
        self.use_launchers = use_launchers
        self._actions: list[Action] = []
        self._initialized = False

    def _wall_filter(self, c: Controller, position: Position) -> bool:
        if not grid.is_valid(c, position):
            return False
        if not c.is_in_vision(position):
            return True

        env = c.get_tile_env(position)
        if env == Environment.WALL:
            return False

        bid = c.get_tile_building_id(position)
        if bid is None:
            return True

        if c.get_team(bid) != c.get_team() or c.get_entity_type(bid) in [
            EntityType.HARVESTER,
            EntityType.CORE,
        ]:
            return False

        return True

    def can_run(self, c: Controller) -> bool:
        return not self._actions or self._actions[-1].can_run(c)

    def run(self, c: Controller) -> TaskResult:
        if not self._initialized:
            north_wall = Position(self.tile.x, self.tile.y - 1)
            south_wall = Position(self.tile.x, self.tile.y + 1)
            east_launcher = Position(self.tile.x + 1, self.tile.y)
            west_launcher = Position(self.tile.x - 1, self.tile.y)

            north_goto = Goto(
                self.global_state,
                [self.tile] + grid.adjacent_positions(c, north_wall),
            )
            south_goto = Goto(
                self.global_state,
                [self.tile] + grid.adjacent_positions(c, south_wall),
            )
            east_goto = Goto(
                self.global_state,
                [self.tile] + grid.adjacent_positions(c, east_launcher),
            )
            west_goto = Goto(
                self.global_state,
                [self.tile] + grid.adjacent_positions(c, west_launcher),
            )

            north_build = BuildBarriers(self.global_state, [north_wall])
            south_build = BuildBarriers(self.global_state, [south_wall])
            east_build = (
                BuildLaunchers(self.global_state, [east_launcher])
                if self.use_launchers
                else BuildBarriers(self.global_state, [east_launcher])
            )
            west_build = (
                BuildLaunchers(self.global_state, [west_launcher])
                if self.use_launchers
                else BuildBarriers(self.global_state, [west_launcher])
            )

            if self._wall_filter(c, north_wall):
                self._actions.extend([north_build, north_goto])
            if self._wall_filter(c, east_launcher):
                self._actions.extend([east_build, east_goto])
            if self._wall_filter(c, south_wall):
                self._actions.extend([south_build, south_goto])
            if self._wall_filter(c, west_launcher):
                self._actions.extend([west_build, west_goto])
            self._initialized = True

        result = run_actions(c, self._actions)
        if result == TaskResult.INCOMPLETE:
            return TaskResult.INCOMPLETE

        return TaskResult.SUCCESS

    def __str__(self) -> str:
        return f"WallOffTile({self.tile})"
