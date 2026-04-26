from __future__ import annotations
from itertools import product
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position, ResourceType

from utils.attacker_states.state import AttackState
from utils.map.raw_map_representation import WALL
from utils.pathfinding.movement import on_map

if TYPE_CHECKING:
    from builders.attacker import Attacker


# Stop hijacking here once this many friendly sentinels are in vision.
_MAX_FRIENDLY_SENTINELS_IN_VISION = 3

# Turns a hard-failed target stays blacklisted before we retry.
_BLACKLIST_TTL = 10

# Give up on an orbit waypoint after this many turns pursuing it.
_ORBIT_STUCK_TURNS = 30

# Chebyshev-radius ring around the enemy core — keeps us circling belts
# rather than beelining at the core.
_ORBIT_RADIUS = 7
_ORBIT_OFFSETS = (
    (0, _ORBIT_RADIUS),
    (5, 5),
    (_ORBIT_RADIUS, 0),
    (5, -5),
    (0, -_ORBIT_RADIUS),
    (-5, -5),
    (-_ORBIT_RADIUS, 0),
    (-5, 5),
)

_HIJACK_TYPES = (EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER)

# Relays that forward resources — traced to see if a candidate conveyor
# ultimately feeds one of our own turrets.
_RELAY_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
})

# A lone splitter relays nothing — only hijack if at least one cardinal
# neighbor is part of a resource network (relay or foundry).
_SPLITTER_NETWORK_TYPES = _RELAY_TYPES | {EntityType.FOUNDRY}
_CARDINAL = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)

_FRIENDLY_TURRET_TYPES = frozenset({EntityType.GUNNER, EntityType.SENTINEL})


def _splitter_is_networked(c: Controller, pos: Position) -> bool:
    for d in _CARDINAL:
        np = pos.add(d)
        if not c.is_in_vision(np):
            continue
        bld_id = c.get_tile_building_id(np)
        if bld_id is None:
            continue
        if c.get_entity_type(bld_id) in _SPLITTER_NETWORK_TYPES:
            return True
    return False


def _chain_feeds_friendly_turret(
    self: Attacker,
    c: Controller,
    start_pos: Position,
    my_team,
) -> bool:
    """Trace relay tiles forward. If any branch reaches a friendly turret,
    blacklist every visited relay and return True. OOV/OOB ends a branch.
    """
    touched: list[tuple[int, int]] = []
    visited: set[tuple[int, int]] = set()
    stack: list[Position] = [start_pos]
    hits_turret = False
    W, H = c.get_map_width(), c.get_map_height()

    while stack:
        pos = stack.pop()
        key = (pos.x, pos.y)
        if key in visited:
            continue
        visited.add(key)

        if (not (0 <= pos.x < W and 0 <= pos.y < H)
                or not c.is_in_vision(pos)
                or (bld_id := c.get_tile_building_id(pos)) is None):
            continue

        etype = c.get_entity_type(bld_id)
        if c.get_team(bld_id) == my_team and etype in _FRIENDLY_TURRET_TYPES:
            hits_turret = True
            continue
        if etype not in _RELAY_TYPES:
            continue

        touched.append(key)
        # Bridges carry a target, not a direction — others have a facing.
        if etype == EntityType.BRIDGE:
            stack.append(c.get_bridge_target(bld_id))
            continue
        facing = c.get_direction(bld_id)
        if facing == Direction.CENTRE:
            continue
        if etype == EntityType.SPLITTER:
            stack += [
                pos.add(facing),
                pos.add(facing.rotate_left().rotate_left()),
                pos.add(facing.rotate_right().rotate_right()),
            ]
        else:
            stack.append(pos.add(facing))

    if hits_turret:
        round_now = c.get_current_round()
        for k in touched:
            self.blacklist[k] = round_now

    return hits_turret


def _pick_target(self: Attacker, c: Controller):
    """Find the best enemy conveyor/bridge currently carrying titanium."""
    my_team = c.get_team()
    me = self.current_pos
    enemy_core = self.enemy_core_pos
    best: Position | None = None
    best_score = float("inf")
    friendly_sentinels = 0

    for bld_id in c.get_nearby_buildings():
        team = c.get_team(bld_id)
        etype = c.get_entity_type(bld_id)

        if team == my_team:
            if etype == EntityType.SENTINEL:
                friendly_sentinels += 1
                if friendly_sentinels >= _MAX_FRIENDLY_SENTINELS_IN_VISION:
                    return None
            continue

        if etype not in _HIJACK_TYPES:
            continue
        if c.get_stored_resource(bld_id) != ResourceType.TITANIUM:
            continue

        conv_pos = c.get_position(bld_id)
        key = (conv_pos.x, conv_pos.y)
        if key in self.blacklist:
            continue

        if etype == EntityType.SPLITTER and not _splitter_is_networked(c, conv_pos):
            continue

        # Skip if any enemy launcher is in the 3x3 pickup ring.
        if any(
            on_map(c, np := Position(conv_pos.x + dx, conv_pos.y + dy))
            and c.is_in_vision(np)
            and (lid := c.get_tile_building_id(np)) is not None
            and c.get_entity_type(lid) == EntityType.LAUNCHER
            and c.get_team(lid) != my_team
            for dx, dy in product((-1, 0, 1), repeat=2)
            if dx or dy
        ):
            continue

        if _chain_feeds_friendly_turret(self, c, conv_pos, my_team):
            # helper already blacklisted the full traced chain
            continue

        dist_me = max(abs(conv_pos.x - me.x), abs(conv_pos.y - me.y))
        score = dist_me * 2
        if enemy_core is not None:
            score += max(abs(conv_pos.x - enemy_core.x),
                         abs(conv_pos.y - enemy_core.y))
            if conv_pos.distance_squared(enemy_core) < 25:
                score -= 1000
        if score < best_score:
            best_score = score
            best = conv_pos

    return best


def _build_orbit(self: Attacker, c: Controller) -> list[Position]:
    """Ring of waypoints at `_ORBIT_RADIUS` around the enemy core."""
    env = self._env_map
    assert env is not None and self.enemy_core_pos is not None
    W, H, ec = c.get_map_width(), c.get_map_height(), self.enemy_core_pos
    pts: list[Position] = []
    for dx, dy in _ORBIT_OFFSETS:
        nx = max(0, min(W - 1, ec.x + dx))
        ny = max(0, min(H - 1, ec.y + dy))
        if env.tile(nx, ny) != WALL:
            pts.append(Position(nx, ny))
    return pts or [ec]


def scan(self: Attacker, c: Controller) -> None:
    """Pick a new target if one is in sight; otherwise probe the map."""
    cutoff = c.get_current_round() - _BLACKLIST_TTL
    self.blacklist = {k: r for k, r in self.blacklist.items() if r >= cutoff}

    if (pick := _pick_target(self, c)) is not None:
        self.target_conveyor = pick
        self._planner_goal = None
        self.state = AttackState.APPROACH
        return

    if self.enemy_core_pos is not None:
        if self.orbit_points is None:
            self.orbit_points = _build_orbit(self, c)
        # Skip past waypoints we're already close to.
        for _ in range(len(self.orbit_points)):
            if self.current_pos.distance_squared(self.orbit_points[self.orbit_idx]) > 20:
                break
            self.orbit_idx = (self.orbit_idx + 1) % len(self.orbit_points)

        # Skip waypoints we've been stuck pursuing for too long.
        round_now = c.get_current_round()
        if self._orbit_pursuit_idx != self.orbit_idx:
            self._orbit_pursuit_idx = self.orbit_idx
            self._orbit_pursuit_round = round_now
        elif round_now - self._orbit_pursuit_round >= _ORBIT_STUCK_TURNS:
            self.orbit_idx = (self.orbit_idx + 1) % len(self.orbit_points)
            self._orbit_pursuit_idx = self.orbit_idx
            self._orbit_pursuit_round = round_now

        self.target_pos = self.orbit_points[self.orbit_idx]
        self._search(c, self.target_pos)
        return

    candidate = self.enemy_core_candidates[self.enemy_core_candidate_idx]
    if self.current_pos.distance_squared(candidate) <= 20:
        self.enemy_core_candidate_idx = (self.enemy_core_candidate_idx + 1) % 3
    self.target_pos = self.enemy_core_candidates[self.enemy_core_candidate_idx]
    self._search(c, self.target_pos)
