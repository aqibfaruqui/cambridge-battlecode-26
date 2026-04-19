from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position, ResourceType

from utils.raw_map_representation import WALL

if TYPE_CHECKING:
    from builders.attacker_revamped import AttackerRevamped


# Cardinal directions only — harvesters feed conveyors along these.
_CARDINALS = (Direction.NORTH, Direction.SOUTH, Direction.EAST, Direction.WEST)

_OPPOSITE = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
}

# Once this many friendly sentinels are already in vision, stop hijacking
# here and fall through to the enemy-core probe so we spread out.
_MAX_FRIENDLY_SENTINELS_IN_VISION = 2

# If a friendly builder bot is within this Chebyshev radius of us, another
# attacker/harvester is probably already working this patch — bail out of
# target picking so we keep orbiting and hit a different part of the belt.
_FRIENDLY_BUILDER_BAIL_RADIUS = 5

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


def _pick_sentinel_tile(self: AttackerRevamped, c: Controller, splitter_pos: Position):
    """Pick an empty cardinally-adjacent tile for the sentinel, preferring
    sides closer to our own core.

    Sentinels only accept ore from cardinally-adjacent tiles, so diagonals
    are never viable. Tiles already occupied by any building are rejected
    outright — we'd rather pick a different target than clear them first.
    Returns None if no candidate passes.
    """
    env = self._env_map
    assert env is not None
    W, H = c.get_map_width(), c.get_map_height()
    core = self.core_pos

    best = None
    best_score = float("inf")
    for d in _CARDINALS:
        dx, dy = d.delta()
        nx, ny = splitter_pos.x + dx, splitter_pos.y + dy
        if nx < 0 or ny < 0 or nx >= W or ny >= H:
            continue
        if env.tile(nx, ny) & (1 << WALL):
            continue
        np = Position(nx, ny)
        if c.is_in_vision(np) and c.get_tile_building_id(np) is not None:
            continue
        if _has_nearby_enemy_launcher(self, c, np):
            continue
        score = max(abs(nx - core.x), abs(ny - core.y))
        if score < best_score:
            best_score = score
            best = np
    return best


def _feeder_dir(c: Controller, conv_pos: Position, my_team) -> Direction | None:
    """Return the direction from a feeding enemy building to conv_pos."""
    for d in _CARDINALS:
        dx, dy = d.delta()
        fp = Position(conv_pos.x - dx, conv_pos.y - dy)
        if not c.is_in_vision(fp):
            continue
        bld_id = c.get_tile_building_id(fp)
        if bld_id is None:
            continue
        if c.get_team(bld_id) == my_team:
            continue
        et = c.get_entity_type(bld_id)
        if et == EntityType.HARVESTER:
            return d
        if et == EntityType.CONVEYOR and c.get_direction(bld_id) == d:
            return d
        if et == EntityType.SPLITTER and c.get_direction(bld_id) != _OPPOSITE[d]:
            return d
    return None


def _has_friendly_builder_nearby(self: AttackerRevamped, c: Controller) -> bool:
    """True if another friendly builder bot is within Chebyshev 9 of us.

    Used as a crowding gate: if a teammate is already working this patch,
    we'd rather keep orbiting than pile onto the same belt.
    """
    me = self.current_pos
    my_id = c.get_id()
    my_team = c.get_team()
    for p in c.get_nearby_tiles():
        if max(abs(p.x - me.x), abs(p.y - me.y)) > _FRIENDLY_BUILDER_BAIL_RADIUS:
            continue
        bot_id = c.get_tile_builder_bot_id(p)
        if bot_id is None or bot_id == my_id:
            continue
        if c.get_team(bot_id) == my_team:
            return True
    return False


def _pick_target(self: AttackerRevamped, c: Controller):
    """Find the best enemy conveyor currently carrying a titanium stack."""
    my_team = c.get_team()
    me = self.current_pos
    enemy_core = self.enemy_core_pos
    best = None
    best_score = float("inf")

    # Spread gate: if a teammate is already on this patch, keep orbiting.
    if _has_friendly_builder_nearby(self, c):
        return None

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
        if c.get_entity_type(bld_id) != EntityType.CONVEYOR:
            continue
        if c.get_stored_resource(bld_id) != ResourceType.TITANIUM:
            continue

        conv_pos = c.get_position(bld_id)
        key = (conv_pos.x, conv_pos.y)
        if key in self.blacklist:
            continue

        # Don't pick a conveyor sitting inside an enemy launcher's pickup ring.
        if _has_nearby_enemy_launcher(self, c, conv_pos):
            continue

        # Find any inbound feeder so we know which side the splitter's back
        # must align with. Skip targets with no visible feeder — we can't
        # place the splitter correctly without this.
        splitter_dir = _feeder_dir(c, conv_pos, my_team)
        if splitter_dir is None:
            continue

        # Must have a reservable adjacent tile for the sentinel.
        sentinel_tile = _pick_sentinel_tile(self, c, conv_pos)
        if sentinel_tile is None:
            continue

        dist_me = max(abs(conv_pos.x - me.x), abs(conv_pos.y - me.y))
        dist_core = max(abs(conv_pos.x - self.core_pos.x),
                        abs(conv_pos.y - self.core_pos.y))
        enemy_penalty = 0
        if enemy_core is not None:
            d_enemy = max(abs(conv_pos.x - enemy_core.x),
                          abs(conv_pos.y - enemy_core.y))
            # Push back on targets deep in enemy territory.
            enemy_penalty = max(0, 6 - d_enemy) * 3

        score = dist_me * 2 + dist_core + enemy_penalty
        if score < best_score:
            best_score = score
            best = (conv_pos, splitter_dir, sentinel_tile)

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
    """Pick a new target if one is in sight; otherwise probe the map.

    Before the enemy core is spotted, we walk toward the symmetry-based
    core candidate. Once it's located, we switch to orbiting a ring around
    it so we sweep past harvester conveyor belts instead of beelining at
    the core itself.
    """
    pick = _pick_target(self, c)
    if pick is not None:
        self.target_conveyor, self.target_direction, self.sentinel_tile = pick
        self._planner_goal = None
        self.state = type(self.state).APPROACH
        return

    if self.enemy_core_pos is not None:
        if self.orbit_points is None:
            self.orbit_points = _build_orbit(self, c)
        waypoint = self.orbit_points[self.orbit_idx]
        if self.current_pos.distance_squared(waypoint) <= 20:
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
