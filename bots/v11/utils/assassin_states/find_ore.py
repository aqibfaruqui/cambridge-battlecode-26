from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position

from utils.assassin_states import AssassinState
from utils.map.raw_map_representation import (
    ORE_TITANIUM, ORE_AXIONITE, TRAVERSABLE, WALL,
)
from utils.pathfinding.movement import DIRECTIONS_4

if TYPE_CHECKING:
    from builders.assassin import Assassin


def find_ore(self: Assassin, c: Controller) -> None:
    """Pick a titanium ore near the enemy core and walk to its stand position."""
    assert self.enemy_core_pos is not None

    if self.target_ore is not None and not _ore_still_valid(self, c, self.target_ore):
        self.ore_blacklist.add((self.target_ore.x, self.target_ore.y))
        self.target_ore = None
        self.target_stand_pos = None

    if self.target_ore is None:
        ore, stand = _pick_target(self, c)
        if ore is None:
            # Nothing known yet — push toward the enemy core to widen vision.
            self.target_pos = self.enemy_core_pos
            self.navigate(c, self.enemy_core_pos, lay_road=True)
            return
        self.target_ore = ore
        self.target_stand_pos = stand

    assert self.target_stand_pos is not None
    if self.current_pos == self.target_stand_pos:
        self.target_gunner_pos = _pick_gunner_pos(self)
        if self.target_gunner_pos is None:
            # Couldn't find a viable gunner tile — try a different ore.
            self.ore_blacklist.add((self.target_ore.x, self.target_ore.y))
            self.target_ore = None
            self.target_stand_pos = None
            return
        self._state = AssassinState.ATTACK
        return

    self.target_pos = self.target_stand_pos
    self.navigate(c, self.target_stand_pos, lay_road=True)


def _ore_still_valid(self: Assassin, c: Controller, ore: Position) -> bool:
    if not c.is_in_vision(ore):
        return True
    if self._env_map.tile(ore.x, ore.y) != ORE_TITANIUM:
        return False
    return _best_stand_pos(self, c, ore) is not None


def _stand_pos_valid(self: Assassin, c: Controller, side: Position) -> bool:
    """Cardinal neighbour of the ore that we can actually stand on."""
    if not self._env_map.in_bounds(side.x, side.y):
        return False
    tile = self._env_map.tile(side.x, side.y)
    if tile in (WALL, ORE_TITANIUM, ORE_AXIONITE):
        return False
    if not c.is_in_vision(side):
        return tile == TRAVERSABLE
    bid = c.get_tile_building_id(side)
    if bid is None:
        return True
    if c.get_team(bid) != c.get_team():
        return False
    return c.get_entity_type(bid) in (EntityType.ROAD, EntityType.MARKER)


def _best_stand_pos(self: Assassin, c: Controller, ore: Position) -> Position | None:
    ec = self.enemy_core_pos
    assert ec is not None
    best, best_dist = None, float("inf")
    for d in DIRECTIONS_4:
        side = ore.add(d)
        if not _stand_pos_valid(self, c, side):
            continue
        dist = max(abs(side.x - ec.x), abs(side.y - ec.y))
        if dist < best_dist:
            best_dist, best = dist, side
    return best


def _speculative_stand_pos(self: Assassin, ore: Position) -> Position | None:
    """For out-of-vision ores: cardinal neighbour closest to enemy core, ignoring buildings."""
    ec = self.enemy_core_pos
    assert ec is not None
    best, best_dist = None, float("inf")
    for d in DIRECTIONS_4:
        side = ore.add(d)
        if not self._env_map.in_bounds(side.x, side.y):
            continue
        if self._env_map.tile(side.x, side.y) in (WALL, ORE_TITANIUM, ORE_AXIONITE):
            continue
        dist = max(abs(side.x - ec.x), abs(side.y - ec.y))
        if dist < best_dist:
            best_dist, best = dist, side
    return best


def _pick_target(self: Assassin, c: Controller) -> tuple[Position | None, Position | None]:
    """Best titanium ore. In-vision-validated outranks speculative; ties broken by Chebyshev to enemy core."""
    ec = self.enemy_core_pos
    assert ec is not None
    candidates: list[tuple[bool, int, Position, Position]] = []
    for (ox, oy) in self._env_map._known_ti:
        if (ox, oy) in self.ore_blacklist:
            continue
        ore = Position(ox, oy)
        in_vision = c.is_in_vision(ore)
        stand = _best_stand_pos(self, c, ore) if in_vision else _speculative_stand_pos(self, ore)
        if stand is None:
            continue
        dist = max(abs(ox - ec.x), abs(oy - ec.y))
        candidates.append((not in_vision, dist, ore, stand))
    if not candidates:
        return None, None
    candidates.sort(key=lambda t: (t[0], t[1]))
    _, _, ore, stand = candidates[0]
    return ore, stand


def _pick_gunner_pos(self: Assassin) -> Position | None:
    """Cardinal neighbour of enemy core that's clear and closest to stand_pos."""
    ec = self.enemy_core_pos
    stand = self.target_stand_pos
    assert ec is not None and stand is not None
    best, best_dist = None, float("inf")
    for d in DIRECTIONS_4:
        gp = ec.add(d)
        if not self._env_map.in_bounds(gp.x, gp.y):
            continue
        if self._env_map.tile(gp.x, gp.y) in (WALL, ORE_TITANIUM, ORE_AXIONITE):
            continue
        dist = max(abs(gp.x - stand.x), abs(gp.y - stand.y))
        if dist < best_dist:
            best_dist, best = dist, gp
    return best
