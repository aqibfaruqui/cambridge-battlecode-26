from __future__ import annotations

import random
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Environment, Position

from utils.attacker_states.state import AttackState
from utils.map.raw_map_representation import CORE_ENEMY, WALL

if TYPE_CHECKING:
    from builders.attacker import Attacker


_CORE_SEARCH_RADIUS_SQ = 50
_PROACTIVE_STUCK_TURNS = 25
_PROACTIVE_REACHED_RADIUS_SQ = 4


def _valid_exploration_point(self: Attacker, c: Controller, pos: Position) -> bool:
    if not (0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()):
        return False
    env = self._env_map
    if env is None:
        return True
    return env.tile(pos.x, pos.y) not in (WALL, CORE_ENEMY)


def _pick_random_exploration_point(self: Attacker, c: Controller) -> Position | None:
    ec = self.enemy_core_pos
    assert ec is not None
    choices: list[Position] = []
    for dx in range(-7, 8):
        for dy in range(-7, 8):
            if dx * dx + dy * dy > _CORE_SEARCH_RADIUS_SQ:
                continue
            pos = Position(ec.x + dx, ec.y + dy)
            if _valid_exploration_point(self, c, pos):
                choices.append(pos)
    if not choices:
        return None
    return random.choice(choices)


def _is_unharvested_titanium(c: Controller, pos: Position) -> bool:
    if not c.is_in_vision(pos):
        return False
    if c.get_tile_env(pos) != Environment.ORE_TITANIUM:
        return False
    bld_id = c.get_tile_building_id(pos)
    return bld_id is None or c.get_entity_type(bld_id) != EntityType.HARVESTER


def _pick_visible_titanium(self: Attacker, c: Controller) -> Position | None:
    ec = self.enemy_core_pos
    assert ec is not None
    best: Position | None = None
    best_score = float("inf")
    for tile in c.get_nearby_tiles():
        if tile.distance_squared(ec) > _CORE_SEARCH_RADIUS_SQ:
            continue
        if not _is_unharvested_titanium(c, tile):
            continue
        if tile != self.current_pos and not c.is_tile_passable(tile):
            continue
        bot_id = c.get_tile_builder_bot_id(tile)
        if bot_id is not None and bot_id != c.get_id():
            continue
        score = self.current_pos.distance_squared(tile)
        if score < best_score:
            best_score = score
            best = tile
    return best


def _raise_on_ore(c: Controller, target: Position) -> None:
    raise RuntimeError(
        f"proactive attacker reached unharvested titanium ore at ({target.x},{target.y})"
    )


def proactive(self: Attacker, c: Controller) -> None:
    """Explore near the enemy core until we can stand on unharvested titanium."""
    if self.enemy_core_pos is None:
        self.proactive_target = None
        self.proactive_ore_target = False
        self.state = AttackState.SCAN
        return

    ore = _pick_visible_titanium(self, c)
    if ore is not None:
        self.proactive_target = ore
        self.proactive_ore_target = True
        self._proactive_pursuit_round = c.get_current_round()
    elif self.proactive_ore_target:
        target = self.proactive_target
        if target is None or (c.is_in_vision(target) and not _is_unharvested_titanium(c, target)):
            self.proactive_target = None
            self.proactive_ore_target = False

    target = self.proactive_target
    round_now = c.get_current_round()
    if (
        target is None
        or (not self.proactive_ore_target and self.current_pos.distance_squared(target) <= _PROACTIVE_REACHED_RADIUS_SQ)
        or round_now - self._proactive_pursuit_round >= _PROACTIVE_STUCK_TURNS
    ):
        target = _pick_random_exploration_point(self, c)
        self.proactive_target = target
        self.proactive_ore_target = False
        self._proactive_pursuit_round = round_now

    if target is None:
        return

    self.target_pos = target
    c.draw_indicator_line(self.current_pos, target, 0, 255, 255)
    if self.proactive_ore_target and self.current_pos == target:
        _raise_on_ore(c, target)

    self._search(c, target)

    if self.proactive_ore_target and c.get_position() == target:
        _raise_on_ore(c, target)
