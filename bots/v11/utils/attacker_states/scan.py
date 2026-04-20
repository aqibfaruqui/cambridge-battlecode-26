from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position, ResourceType

from utils.map.raw_map_representation import WALL

if TYPE_CHECKING:
    from builders.attacker_revamped import AttackerRevamped


# Once this many friendly sentinels are already in vision, stop hijacking
# here and fall through to the enemy-core probe so we spread out.
_MAX_FRIENDLY_SENTINELS_IN_VISION = 3

# How many turns a hard-failed target stays blacklisted before we retry it.
_BLACKLIST_TTL = 30


def _expire_blacklist(self: AttackerRevamped, c: Controller) -> None:
    cutoff = c.get_current_round() - _BLACKLIST_TTL
    stale = [k for k, r in self.blacklist.items() if r < cutoff]
    for k in stale:
        del self.blacklist[k]

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


def _has_nearby_enemy_launcher(self: AttackerRevamped, c: Controller, pos: Position) -> bool:
    """Any enemy launcher in the 3x3 around pos (the pickup range)."""
    my_team = c.get_team()
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


_HIJACK_TYPES = (EntityType.CONVEYOR, EntityType.BRIDGE)


def _pick_target(self: AttackerRevamped, c: Controller):
    """Find the best enemy conveyor/bridge currently carrying a titanium stack."""
    my_team = c.get_team()
    me = self.current_pos
    enemy_core = self.enemy_core_pos
    best: Position | None = None
    best_score = float("inf")

    nearby = c.get_nearby_buildings()

    friendly_sentinels = 0
    for bld_id in nearby:
        if (c.get_team(bld_id) == my_team
                and c.get_entity_type(bld_id) == EntityType.SENTINEL):
            friendly_sentinels += 1
            if friendly_sentinels >= _MAX_FRIENDLY_SENTINELS_IN_VISION:
                return None

    for bld_id in nearby:
        if c.get_team(bld_id) == my_team:
            continue
        if c.get_entity_type(bld_id) not in _HIJACK_TYPES:
            continue
        if c.get_stored_resource(bld_id) != ResourceType.TITANIUM:
            continue

        conv_pos = c.get_position(bld_id)
        key = (conv_pos.x, conv_pos.y)
        if key in self.blacklist:
            continue

        if _has_nearby_enemy_launcher(self, c, conv_pos):
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
        self.state = type(self.state).APPROACH
        return

    if self.enemy_core_pos is not None:
        if self.orbit_points is None:
            self.orbit_points = _build_orbit(self, c)
        for _ in range(len(self.orbit_points)):
            waypoint = self.orbit_points[self.orbit_idx]
            if self.current_pos.distance_squared(waypoint) > 20:
                break
            self.orbit_idx = (self.orbit_idx + 1) % len(self.orbit_points)
        waypoint = self.orbit_points[self.orbit_idx]
        self.target_pos = waypoint
        self._search(c, waypoint)
        return

    idx = self.enemy_core_candidate_idx
    candidate = self.enemy_core_candidates[idx]
    if self.current_pos.distance_squared(candidate) <= 20:
        self.enemy_core_candidate_idx = (idx + 1) % 3
    self.target_pos = self.enemy_core_candidates[self.enemy_core_candidate_idx]
    self._search(c, self.target_pos)
