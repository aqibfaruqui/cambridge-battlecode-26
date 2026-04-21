from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position, ResourceType

from utils.attacker_states.state import AttackState
from utils.map.raw_map_representation import WALL

if TYPE_CHECKING:
    from builders.attacker_revamped import AttackerRevamped


# Once this many friendly sentinels are already in vision, stop hijacking
# here and fall through to the enemy-core probe so we spread out.
_MAX_FRIENDLY_SENTINELS_IN_VISION = 3

# How many turns a hard-failed target stays blacklisted before we retry it.
_BLACKLIST_TTL = 30

# Give up on an orbit waypoint after this many turns pursuing it.
_ORBIT_STUCK_TURNS = 30

# Chebyshev-radius ring around the enemy core used as SCAN waypoints once
# the core is spotted — keeps the attacker circling harvester belts rather
# than beelining at the core itself.
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

_HIJACK_TYPES = (EntityType.CONVEYOR, EntityType.BRIDGE)

# Relays that forward resources — traced through when checking whether a
# candidate conveyor/bridge ultimately feeds one of our own turrets.
_RELAY_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
})

_FRIENDLY_TURRET_TYPES = frozenset({EntityType.GUNNER, EntityType.SENTINEL})


def _chain_feeds_friendly_turret(
    self: AttackerRevamped,
    c: Controller,
    start_pos: Position,
    my_team,
) -> bool:
    """Trace resource flow forward from start_pos through relay tiles.

    Returns True iff some path reaches a friendly gunner/sentinel; in that
    case every relay tile walked through is added to self.blacklist so we
    also skip those candidates in this and future scans.

    Unknown tiles (out of vision, OOB) terminate a branch as safe.
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

        if not (0 <= pos.x < W and 0 <= pos.y < H):
            continue
        if not c.is_in_vision(pos):
            continue

        bld_id = c.get_tile_building_id(pos)
        if bld_id is None:
            continue

        etype = c.get_entity_type(bld_id)
        if c.get_team(bld_id) == my_team and etype in _FRIENDLY_TURRET_TYPES:
            hits_turret = True
            continue

        if etype not in _RELAY_TYPES:
            continue

        touched.append(key)

        if etype == EntityType.BRIDGE:
            stack.append(c.get_bridge_target(bld_id))
            continue

        facing = c.get_direction(bld_id)
        if facing == Direction.CENTRE:
            continue

        if etype == EntityType.SPLITTER:
            # Splitter outputs to facing + two perpendicular cardinals.
            stack.append(pos.add(facing))
            stack.append(pos.add(facing.rotate_left().rotate_left()))
            stack.append(pos.add(facing.rotate_right().rotate_right()))
        else:
            # CONVEYOR / ARMOURED_CONVEYOR: single output in facing direction.
            stack.append(pos.add(facing))

    if hits_turret:
        round_now = c.get_current_round()
        for k in touched:
            self.blacklist[k] = round_now

    return hits_turret


def _expire_blacklist(self: AttackerRevamped, c: Controller) -> None:
    cutoff = c.get_current_round() - _BLACKLIST_TTL
    stale = [k for k, r in self.blacklist.items() if r < cutoff]
    for k in stale:
        del self.blacklist[k]


def _has_nearby_enemy_launcher(c: Controller, pos: Position, my_team) -> bool:
    """Any enemy launcher in the 3x3 around pos (the pickup range)."""
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            np = Position(pos.x + dx, pos.y + dy)
            if not c.is_in_vision(np):
                continue
            bld_id = c.get_tile_building_id(np)
            if bld_id is None:
                continue
            if (c.get_entity_type(bld_id) == EntityType.LAUNCHER
                    and c.get_team(bld_id) != my_team):
                return True
    return False


def _pick_target(self: AttackerRevamped, c: Controller):
    """Find the best enemy conveyor/bridge currently carrying a titanium stack."""
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
        if _has_nearby_enemy_launcher(c, conv_pos, my_team):
            continue
        if _chain_feeds_friendly_turret(self, c, conv_pos, my_team):
            # helper already blacklisted the full traced chain
            continue

        dist_me = max(abs(conv_pos.x - me.x), abs(conv_pos.y - me.y))
        dist_core = max(abs(conv_pos.x - self.core_pos.x),
                        abs(conv_pos.y - self.core_pos.y))
        score = dist_me * 2 + dist_core
        if enemy_core is not None and conv_pos.distance_squared(enemy_core) < 25:
            score -= 1000
        if score < best_score:
            best_score = score
            best = conv_pos

    return best


def _build_orbit(self: AttackerRevamped, c: Controller) -> list[Position]:
    """Ring of waypoints at `_ORBIT_RADIUS` around the enemy core"""
    env = self._env_map
    assert env is not None and self.enemy_core_pos is not None
    W, H = c.get_map_width(), c.get_map_height()
    ec = self.enemy_core_pos
    pts: list[Position] = []
    for dx, dy in _ORBIT_OFFSETS:
        nx = max(0, min(W - 1, ec.x + dx))
        ny = max(0, min(H - 1, ec.y + dy))
        if env.tile(nx, ny) & (1 << WALL):
            continue
        pts.append(Position(nx, ny))
    return pts or [ec]


def _scan(self: AttackerRevamped, c: Controller) -> None:
    """Pick a new target if one is in sight; otherwise probe the map."""
    _expire_blacklist(self, c)
    pick = _pick_target(self, c)
    if pick is not None:
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
