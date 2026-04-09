from enum import IntEnum
import random

from action.interface import Behaviour
from action.build import BuildBarriers
from action.composed.wall_off_tile import WallOffTile
from action.navigation import Goto
from cambc import Controller, Position, Environment, EntityType
import grid
from world.tracking import find_enemy_core_pos


class ForceKillerState(IntEnum):
    IDLE = 1
    KILL = 2


class ForceKiller(Behaviour):
    def __init__(self):
        super().__init__()
        self._state = ForceKillerState.IDLE
        self._enemy_core_pos = None

    def _next_location(self, c: Controller) -> Position:
        x = random.randint(0, c.get_map_width() - 1)
        y = random.randint(0, c.get_map_height() - 1)
        return Position(x, y)

    def tick(self, c: Controller) -> None:
        self._enemy_core_pos = find_enemy_core_pos(c, self._enemy_core_pos)
        super().tick(c)

    def _make_block_ore_actions(
        self, c: Controller, candidate: Position
    ) -> tuple[WallOffTile, Goto]:
        return (
            WallOffTile(candidate, use_launchers=False),
            Goto(grid.adjacent_positions(c, candidate)),
        )

    def _set_block_task(self, c: Controller, candidate: Position) -> None:
        if any(isinstance(a, (BuildBarriers, WallOffTile)) for a in self.actions):
            return

        wall_off, goto = self._make_block_ore_actions(c, candidate)
        self.actions.extend([wall_off, goto])

    def _set_kill_task(self, c: Controller, ore: Position) -> None:
        return

    def check_interrupts(self, c: Controller) -> None:
        if self._state == ForceKillerState.IDLE:
            if (
                c.get_current_round() > 200
                and self._enemy_core_pos is not None
            ):
                self._state = ForceKillerState.KILL
                return

            ores = sorted(
                (
                    ore
                    for ore in c.get_nearby_tiles()
                    if c.get_tile_env(ore) == Environment.ORE_TITANIUM
                    and c.get_tile_building_id(ore) is None
                ),
                key=lambda p: c.get_position().distance_squared(p),
            )

            if ores:
                self._set_block_task(c, ores[0])
        elif self._state == ForceKillerState.KILL:
            ores = sorted(
                (
                    ore
                    for ore in c.get_nearby_tiles()
                    if c.get_tile_env(ore) == Environment.ORE_TITANIUM
                    and c.get_tile_building_id(ore) is not None
                    and c.get_entity_type(c.get_tile_building_id(ore))
                    == EntityType.BARRIER
                    and c.get_team(c.get_tile_building_id(ore)) == c.get_team()
                ),
                key=lambda p: c.get_position().distance_squared(p),
            )
            if ores:
                self._set_kill_task(c, ores[0])

    def check_transitions(self, c: Controller) -> None:
        pass

    def idle(self, c: Controller) -> None:
        if not self.actions:
            ti, ax = c.get_global_resources()
            if ti < 300:
                return
            next_location = self._next_location(c)
            self.actions.append(
                Goto([next_location], clear_roads_behind=True)
            )
