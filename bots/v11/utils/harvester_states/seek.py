from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, Controller

from utils.pathfinding.d_star import DStarLite, _SEEK_BLOCK_MASK
from utils.map.raw_map_representation import ORE_AXIONITE, ORE_TITANIUM
from utils.pathfinding.movement import DIRECTIONS_4, _chebyshev, random_direction_4
from utils.comms.for_builder_bot import BuilderBotMessages, BuilderBotMessageType

if TYPE_CHECKING:
    from builders.harvester import Harvester


def _find_damaged_conveyor(c: Controller) -> Position | None:
    """Scan all buildings in vision for the most-damaged allied conveyor or bridge."""
    my_team = c.get_team()
    best_pos: Position | None = None
    best_ratio = float("inf")
    for bid in c.get_nearby_buildings():
        if c.get_team(bid) != my_team:
            continue
        if c.get_entity_type(bid) not in (EntityType.CONVEYOR, EntityType.BRIDGE):
            continue
        max_hp = c.get_max_hp(bid)
        hp = c.get_hp(bid)
        if hp >= max_hp:
            continue
        ratio = hp / max_hp
        if ratio < best_ratio:
            best_ratio = ratio
            best_pos = c.get_position(bid)
    return best_pos


def _ensure_seek_blacklists(self) -> None:
    if not hasattr(self, "blacklisted_seek_targets"):
        self.blacklisted_seek_targets = set()
    if not hasattr(self, "seek_unreachable_counts"):
        self.seek_unreachable_counts = {}
    if not hasattr(self, "seek_stall_target"):
        self.seek_stall_target = None
    if not hasattr(self, "seek_target_turns"):
        self.seek_target_turns = 0


def _read_nearby_claims(c: Controller) -> set[tuple[int, int]]:
    claimed: set[tuple[int, int]] = set()
    my_team = c.get_team()
    for pos in c.get_nearby_tiles():
        mid = c.get_tile_building_id(pos)
        if mid is None:
            continue
        if c.get_entity_type(mid) != EntityType.MARKER:
            continue
        if c.get_team(mid) != my_team:
            continue
        value = c.get_marker_value(mid)
        msg_type = BuilderBotMessages.get_message_type(value)
        if msg_type == BuilderBotMessageType.CLAIM_ORE:
            target = BuilderBotMessages.decode_claim_ore(value)
        elif msg_type == BuilderBotMessageType.CLAIM_POSITION:
            target = BuilderBotMessages.decode_claim_position(value)
        else:
            continue
        claimed.add((target.x, target.y))
    return claimed


_DEGENERATE_ROOM = 3


def _explore_lane(self: Harvester, c: Controller) -> tuple[str, int]:
    """Assign a soft exploration lane so harvesters peel away from each other."""
    env = self.environment_map
    if env is None:
        return "x", 1

    cx, cy = self.core_pos.x, self.core_pos.y
    w, h = env.width, env.height

    left_room  = cx
    right_room = w - 1 - cx
    up_room    = cy
    down_room  = h - 1 - cy

    # An axis is "splittable" only when there is meaningful room on BOTH sides.
    # If the core is near an edge, splitting along that axis sends one harvester
    # into the wall — use the other axis instead.
    x_splittable = left_room > _DEGENERATE_ROOM and right_room > _DEGENERATE_ROOM
    y_splittable = up_room   > _DEGENERATE_ROOM and down_room  > _DEGENERATE_ROOM

    # Derive direction from which side of the core this harvester spawned on.
    spawn = self.spawn_pos if self.spawn_pos is not None else self.current_pos
    dx = spawn.x - cx
    dy = spawn.y - cy

    if x_splittable and y_splittable:
        horizontal_balance = min(left_room, right_room)
        vertical_balance   = min(up_room,   down_room)
        if horizontal_balance > vertical_balance:
            axis = "x"
        elif vertical_balance > horizontal_balance:
            axis = "y"
        else:
            axis = "x" if w >= h else "y"
        sign = (1 if dx >= 0 else -1) if axis == "x" else (1 if dy >= 0 else -1)
        return axis, sign

    if x_splittable:
        return "x", 1 if dx >= 0 else -1

    if y_splittable:
        return "y", 1 if dy >= 0 else -1

    # Corner core: use the dominant spawn offset to pick axis and direction.
    if abs(dx) >= abs(dy):
        return "x", 1 if dx >= 0 else -1
    return "y", 1 if dy >= 0 else -1


def _ore_lane_score(
    self: Harvester,
    pos: Position,
    ore_pos: Position,
    lane_axis: str,
    lane_sign: int,
) -> float:
    """Score an ore candidate: prefer ores on this harvester's assigned lane side."""
    if lane_axis == "x":
        preferred_offset = ore_pos.x - self.core_pos.x
    else:
        preferred_offset = ore_pos.y - self.core_pos.y

    if preferred_offset * lane_sign > 0:
        lane_bonus = 20.0
    elif preferred_offset * lane_sign < 0:
        lane_bonus = -20.0
    else:
        lane_bonus = 0.0

    return lane_bonus - _chebyshev(pos, ore_pos)


def _seek_dynamic_blockers(self: Harvester, c: Controller, move_target: Position) -> list[tuple[int, int]]:
    blocked: list[tuple[int, int]] = []
    my_id = c.get_id()
    for pos in c.get_nearby_tiles():
        if pos == self.current_pos:
            continue
        bot_id = c.get_tile_builder_bot_id(pos)
        if bot_id is None or bot_id == my_id:
            continue
        blocked.append((pos.x, pos.y))
    return blocked


def _is_memory_passable(self: Harvester, x: int, y: int) -> bool:
    env = self.environment_map
    if env is None or not env.in_bounds(x, y):
        return False
    return env.is_frontier_passable(x, y)


def _best_ore_approach(
    self: Harvester, 
    ore_pos: Position, 
    origin: Position | None = None, 
    c: Controller | None = None
) -> Position | None:
    """Pick the best adjacent tile from which to build the harvester"""
    if origin is None:
        origin = self.current_pos
    env = self.environment_map
    if env is None:
        return None

    best_target = None
    best_dist = float("inf")

    # Choose the closest viable cardinal build tile around the ore.
    for direction in DIRECTIONS_4:
        candidate = ore_pos.add(direction)
        if candidate == origin:
            return candidate

        if not env.in_bounds(candidate.x, candidate.y):
            continue
        if not env.is_seek_candidate(candidate.x, candidate.y):
            continue
        if c is not None and c.is_in_vision(candidate):
            occupier = c.get_tile_builder_bot_id(candidate)
            if occupier is not None and occupier != c.get_id():
                continue

        dist = _chebyshev(origin, candidate)
        if dist < best_dist:
            best_dist = dist
            best_target = candidate

    return best_target


def _frontier_score(
    self: Harvester,
    pos: Position,
    target: Position,
    lane_axis: str,
    lane_sign: int,
) -> float:
    """Score a frontier tile by exploration value and nearby ore density"""
    env = self.environment_map
    if env is None:
        return float("-inf")

    distance = pos.distance_squared(target) or 1
    unknown_neighbors = 0
    ore_neighbors = 0

    for direction in DIRECTIONS_4:
        neighbor = target.add(direction)
        if not env.in_bounds(neighbor.x, neighbor.y):
            continue
        state = env.tile(neighbor.x, neighbor.y)
        if env.is_unknown(neighbor.x, neighbor.y):
            unknown_neighbors += 1
        elif state == ORE_TITANIUM:
            ore_neighbors += 1

    width_mid = env.width // 2
    height_mid = env.height // 2
    quadrant_bonus = 0
    if (target.x < width_mid) != (self.core_pos.x < width_mid):
        quadrant_bonus += 1
    if (target.y < height_mid) != (self.core_pos.y < height_mid):
        quadrant_bonus += 1

    preferred_offset = target.x - self.core_pos.x
    cross_offset = target.y - self.core_pos.y
    if lane_axis == "y":
        preferred_offset, cross_offset = cross_offset, preferred_offset

    lane_bonus = 0.0
    if preferred_offset != 0:
        lane_distance = abs(preferred_offset)
        lane_strength = max(20, 120 - (lane_distance * 8))
        if preferred_offset * lane_sign > 0:
            lane_bonus += lane_strength
        else:
            lane_bonus -= lane_strength * 0.75

    # Avoid reusing the same narrow exit corridor near the core when a side lane exists.
    core_distance = max(abs(target.x - self.core_pos.x), abs(target.y - self.core_pos.y))
    if core_distance <= 5 and abs(cross_offset) <= 1:
        if preferred_offset * lane_sign <= 0:
            lane_bonus -= 45

    return (unknown_neighbors * 80 + ore_neighbors * 50 + quadrant_bonus * 30 + lane_bonus) - distance


def _pick_frontier_target(
    self: Harvester,
    pos: Position,
    lane_axis: str,
    lane_sign: int,
    claimed: set[tuple[int, int]] | None = None,
) -> Position | None:
    """Pick the best frontier tile to continue exploration"""
    env = self.environment_map
    if env is None:
        return None

    # Coarse scan keeps SEEK target picking cheap on large maps.
    stride = 2
    phase = self.edge_cycle_index % stride
    self.edge_cycle_index += 1
    best_target = None
    best_score = float("-inf")
    _ensure_seek_blacklists(self)
    blocked = set(self.blacklisted_seek_targets)
    if claimed:
        blocked |= claimed

    # Frontier tiles are known-passable tiles bordering unseen space.
    for y in range(phase, env.height, stride):
        for x in range(phase, env.width, stride):
            if (x, y) in blocked:
                continue
            if not _is_memory_passable(self, x, y):
                continue

            target = Position(x, y)
            for direction in DIRECTIONS_4:
                neighbor = target.add(direction)
                if not env.in_bounds(neighbor.x, neighbor.y):
                    continue
                if not env.is_unknown(neighbor.x, neighbor.y):
                    continue

                score = _frontier_score(self, pos, target, lane_axis, lane_sign)
                if score > best_score:
                    best_score = score
                    best_target = target
                break

    return best_target


def _fallback_edge_target(self: Harvester, lane_axis: str, lane_sign: int) -> Position:
    """Cycle through edge midpoints if no better exploration target exists"""
    env = self.environment_map
    if env is None:
        return self.current_pos.add(random_direction_4())
    w = env.width
    h = env.height
    north = Position(w // 2, 0)
    east = Position(w - 1, h // 2)
    south = Position(w // 2, h - 1)
    west = Position(0, h // 2)
    if lane_axis == "x":
        primary = [east, west] if lane_sign > 0 else [west, east]
        secondary = [south, north]
    else:
        primary = [south, north] if lane_sign > 0 else [north, south]
        secondary = [east, west]
    targets = primary + secondary
    _ensure_seek_blacklists(self)
    for _ in range(len(targets)):
        target = targets[self.edge_cycle_index % len(targets)]
        self.edge_cycle_index += 1
        if (target.x, target.y) not in self.blacklisted_seek_targets:
            return target
    return targets[(self.edge_cycle_index - 1) % len(targets)]


def _collect_ore_candidates(fetch_fn, blocked: set) -> list[Position]:
    """Drain fetch_fn (nearest-ore query) into a list, skipping already-blocked positions."""
    candidates: list[Position] = []
    tmp = set(blocked)
    while True:
        ore = fetch_fn(tmp)
        if ore is None:
            break
        candidates.append(ore)
        tmp.add((ore.x, ore.y))
    return candidates


def _pick_seek_target(
    self: Harvester,
    pos: Position,
    c: Controller,
    claimed: set[tuple[int, int]] | None = None,
) -> tuple[Position | None, bool]:
    """Choose between known titanium, predicted titanium, and frontier exploration."""
    env = self.environment_map
    if env is None:
        return pos.add(random_direction_4()), False

    _ensure_seek_blacklists(self)
    blocked = set(self.blacklisted_ores) | set(self.blacklisted_seek_targets)
    if claimed:
        blocked |= claimed

    lane_axis, lane_sign = _explore_lane(self, c)

    def score(p: Position) -> float:
        return _ore_lane_score(self, pos, p, lane_axis, lane_sign)

    # --- 1. Confirmed (observed) titanium, lane-biased ---
    candidates = _collect_ore_candidates(
        lambda tmp: env.nearest_known_titanium(pos, tmp, observed_only=True), blocked
    )
    for ti in sorted(candidates, key=score, reverse=True):
        if _best_ore_approach(self, ti, pos) is not None:
            return ti, True
        key = (ti.x, ti.y)
        self.blacklisted_ores.add(key)
        blocked.add(key)

    # --- 2. Symmetry-predicted titanium, lane-biased ---
    if env.symmetry is not None:
        candidates = _collect_ore_candidates(
            lambda tmp: env.nearest_predicted_titanium(pos, tmp), blocked
        )
        for ti in sorted(candidates, key=score, reverse=True):
            if _best_ore_approach(self, ti, pos) is not None:
                return ti, True
            key = (ti.x, ti.y)
            self.blacklisted_ores.add(key)
            blocked.add(key)

    # --- 3. Axionite (once titanium is secured) ---
    if self.titanium_found and not self.axionite_found and not self.foundry_prev_placed:
        candidates = _collect_ore_candidates(
            lambda tmp: env.nearest_known_axionite(pos, tmp), blocked
        )
        for ax in sorted(candidates, key=score, reverse=True):
            if _best_ore_approach(self, ax, pos) is not None:
                return ax, True
            key = (ax.x, ax.y)
            self.blacklisted_ores.add(key)
            blocked.add(key)

    # --- 4. Frontier exploration ---
    frontier = _pick_frontier_target(self, pos, lane_axis, lane_sign, claimed)
    if frontier is not None:
        return frontier, False

    return _fallback_edge_target(self, lane_axis, lane_sign), False


def _target_still_viable(self: Harvester, target: Position, is_ore_target: bool) -> bool:
    env = self.environment_map
    if env is None:
        return False
    if not env.in_bounds(target.x, target.y):
        return False
    if is_ore_target:
        return env.tile(target.x, target.y) in (ORE_TITANIUM, ORE_AXIONITE)
    # Frontier exploration targets expire once reached or once fully revealed.
    if target == self.current_pos:
        return False
    for direction in DIRECTIONS_4:
        neighbor = target.add(direction)
        if env.in_bounds(neighbor.x, neighbor.y) and env.is_unknown(neighbor.x, neighbor.y):
            return True
    return False


def _can_execute_seek_step(self: Harvester, c: Controller, move_dir: Direction) -> bool:
    next_pos = self.current_pos.add(move_dir)
    if c.can_move(move_dir):
        return True
    if not (0 <= next_pos.x < c.get_map_width() and 0 <= next_pos.y < c.get_map_height()):
        return False
    if c.get_tile_env(next_pos) != Environment.EMPTY:
        return False
    build_id = c.get_tile_building_id(next_pos)
    if build_id is not None and c.get_entity_type(build_id) == EntityType.MARKER:
        return True
    return c.can_build_road(next_pos)


def _seek_direction(self: Harvester, c: Controller, move_target: Position) -> Direction | None:
    w = c.get_map_width()
    h = c.get_map_height()
    if w <= 0 or h <= 0:
        return None

    # Guard D* goal construction against out-of-bounds exploration targets.
    if not (0 <= move_target.x < w and 0 <= move_target.y < h):
        move_target = Position(
            min(max(move_target.x, 0), w - 1),
            min(max(move_target.y, 0), h - 1),
        )

    if self.environment_map is not None:
        goal = (move_target.x, move_target.y)
        planner = self.seek_planner

        if planner is None or self.seek_planner_goal != goal:
            planner = DStarLite(self.environment_map, move_target.x, move_target.y, block_mask=_SEEK_BLOCK_MASK)
            self.seek_planner = planner
            self.seek_planner_goal = goal

        planner.set_position(self.current_pos.x, self.current_pos.y)
        planner.set_dynamic_blockers(_seek_dynamic_blockers(self, c, move_target))
        planner.notify_map_changes()

        move_dir = planner.step()
        if (
            move_dir is not None
            and move_dir != Direction.CENTRE
            and _can_execute_seek_step(self, c, move_dir)
        ):
            return move_dir

    return None


def _seek(self: Harvester, c: Controller):
    """Explore, target ore, and place harvesters when adjacent"""
    _ensure_seek_blacklists(self)

    if self._try_build_harvester(c):
        return

    # Validate existing heal target
    if self.heal_target is not None:
        bid = c.get_tile_building_id(self.heal_target)
        if (
            bid is None
            or c.get_team(bid) != c.get_team()
            or c.get_entity_type(bid) not in (EntityType.CONVEYOR, EntityType.BRIDGE)
            or c.get_hp(bid) >= c.get_max_hp(bid)
        ):
            self.heal_target = None

    # Scan vision for a new target if we don't have one
    if self.heal_target is None:
        self.heal_target = _find_damaged_conveyor(c)

    # Pursue heal target: move toward it and heal when in range
    if self.heal_target is not None:
        if self.current_pos.distance_squared(self.heal_target) <= 2:
            if c.get_action_cooldown() == 0 and c.can_heal(self.heal_target):
                c.heal(self.heal_target)
        else:
            move_dir = _seek_direction(self, c, self.heal_target)
            self._advance(c, move_dir)
        return

    claimed = _read_nearby_claims(c)

    if self.target_pos is None or not _target_still_viable(self, self.target_pos, self.seek_target_is_ore):
        self.target_pos, self.seek_target_is_ore = _pick_seek_target(
            self,
            self.current_pos,
            c,
            claimed,
        )
        if self.target_pos is None:
            return

    # Stall detection: if we've chased this target for 50 turns without success,
    # blacklist it and reset so a new target gets picked next turn.
    if self.seek_stall_target == self.target_pos:
        self.seek_target_turns += 1
    else:
        self.seek_stall_target = self.target_pos
        self.seek_target_turns = 1
    if self.seek_target_turns >= 50:
        key = (self.target_pos.x, self.target_pos.y)
        if self.seek_target_is_ore:
            self.blacklisted_ores.add(key)
        else:
            self.blacklisted_seek_targets.add(key)
        self.target_pos = None
        self.seek_target_is_ore = False
        self.seek_stall_target = None
        self.seek_target_turns = 0
        return

    move_target = self.target_pos
    is_ore_target = self.seek_target_is_ore
    if is_ore_target:
        # Drop ores that are already claimed when they come into vision.
        if c.is_in_vision(self.target_pos) and not self._is_valid_ore_target(c, self.target_pos):
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
            return

        # Move to an adjacent build tile, not onto the ore itself.
        move_target = _best_ore_approach(self, self.target_pos, c=c)
        if move_target is None:
            self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
            return
    elif move_target == self.current_pos:
        # Reached a non-ore exploration waypoint; pick a fresh frontier target.
        self.target_pos = None
        self.seek_target_is_ore = False
        return

    move_dir = _seek_direction(self, c, move_target)
    if move_dir is None:
        # Blacklist tiles that repeatedly prove unreachable for D*.
        key = (move_target.x, move_target.y)
        misses = self.seek_unreachable_counts.get(key, 0) + 1
        self.seek_unreachable_counts[key] = misses
        miss_limit = 5
        if not is_ore_target:
            miss_limit = 8
        if misses >= miss_limit:
            self.blacklisted_seek_targets.add(key)
            self.seek_unreachable_counts.pop(key, None)
            if is_ore_target:
                self.blacklisted_ores.add((self.target_pos.x, self.target_pos.y))
            self.target_pos = None
            self.seek_target_is_ore = False
        return

    self.seek_unreachable_counts.pop((move_target.x, move_target.y), None)

    if self.seek_target_is_ore:
        claim_value = BuilderBotMessages.encode_claim_ore(self.target_pos)
    else:
        claim_value = BuilderBotMessages.encode_claim_position(self.target_pos)
    best_claim_tile = None
    best_claim_dist = float("inf")
    for _mp in c.get_nearby_tiles():
        if not c.can_place_marker(_mp):
            continue
        d = _chebyshev(_mp, self.target_pos)
        if d < best_claim_dist:
            best_claim_dist = d
            best_claim_tile = _mp
    if best_claim_tile is not None:
        c.place_marker(best_claim_tile, claim_value)

    self._advance(c, move_dir)
