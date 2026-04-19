from enum import Enum
from cambc import Controller, Direction, EntityType, Position
from utils.pathfinding.d_star import DStarLite
from utils.map.raw_map_representation import (
    EnvironmentMap,
    Symmetry,
    WALL,
)

# Allows UNKNOWN, TRAVERSABLE, CORE_OWN, and CORE_ENEMY so the attacker can
# path to/through enemy territory.  _SEEK_BLOCK_MASK cannot be reused here
# because it blocks ENEMY_CORE tiles, making the enemy core unreachable as a goal.
_ATTACK_BLOCK_MASK = (1 << WALL)


class AttackState(Enum):
    __slots__ = ()

    NAVIGATE = "navigate"
    PLACE_SELF_DESTRUCT = "place_self_destruct"
    DONE = "done"


class Attacker:
    def __init__(self, core_pos: Position):
        self.state = AttackState.NAVIGATE
        self.core_pos = core_pos
        self.enemy_pos: Position | None = None
        self.current_pos: Position = core_pos
        self.attack_target: Position | None = None
        self.turret_target: Position | None = None
        self.gunners_placed = 0
        self.enemy_core_candidate_idx = 0
        self.enemy_core_candidates: list[Position] = []
        self._env_map: EnvironmentMap | None = None
        self._planner: DStarLite | None = None
        self._planner_goal: tuple[int, int] | None = None
        self.target_pos: Position | None = None

    def _search(self, c: Controller, target: Position):
        """Helper: navigate towards target with D* Lite and pave if needed."""
        if c.get_move_cooldown() > 0:
            return

        env_map = self._env_map
        assert env_map is not None
        pos = c.get_position()
        goal = (target.x, target.y)
        if self._planner is None or self._planner_goal != goal:
            self._planner = DStarLite(
                env_map, target.x, target.y, block_mask=_ATTACK_BLOCK_MASK
            )
            self._planner_goal = goal

        my_id = c.get_id()
        my_team = c.get_team()
        blockers: list[tuple[int, int]] = []
        for p in c.get_nearby_tiles():
            # Other builder bots physically block movement — route around them
            bot_id = c.get_tile_builder_bot_id(p)
            if bot_id is not None and bot_id != my_id:
                blockers.append((p.x, p.y))
                continue
            bld_id = c.get_tile_building_id(p)
            if bld_id is None:
                continue
            entity_type = c.get_entity_type(bld_id)
            # Harvesters are physically impassable for builder bots
            if entity_type == EntityType.HARVESTER:
                blockers.append((p.x, p.y))
                continue
            # Enemy core is impassable (only the allied core is in the passable list)
            if entity_type == EntityType.CORE and c.get_team(bld_id) != my_team:
                blockers.append((p.x, p.y))

        self._planner.set_position(pos.x, pos.y)
        self._planner.set_dynamic_blockers(blockers)
        self._planner.notify_map_changes()
        direction = self._planner.step()

        if direction is None or direction == Direction.CENTRE:
            return

        next_pos = pos.add(direction)

        if c.get_action_cooldown() == 0 and c.can_build_road(next_pos):
            c.build_road(next_pos)

        if c.can_move(direction):
            c.move(direction)

    def _navigate(self, c: Controller):
        """Navigate towards {self.attack_target} next to enemy core"""
        if self.enemy_pos is not None:
            attack_target = self.attack_target
            assert attack_target is not None
            self.target_pos = attack_target
            if self.current_pos.distance_squared(attack_target) <= 4:
                self.state = AttackState.PLACE_SELF_DESTRUCT
            else:
                self._search(c, attack_target)
        else:
            # Cycle through candidates
            if (
                self.current_pos.distance_squared(
                    self.enemy_core_candidates[self.enemy_core_candidate_idx]
                )
                <= 20
            ):
                self.enemy_core_candidate_idx = (self.enemy_core_candidate_idx + 1) % 3
            self.target_pos = self.enemy_core_candidates[self.enemy_core_candidate_idx]
            self._search(c, self.target_pos)

    def _place_self_destruct(self, c: Controller):
        """Look for enemy logistics near the enemy core and self destruct"""
        env_map = self._env_map
        enemy_pos = self.enemy_pos
        assert env_map is not None
        assert enemy_pos is not None
        me = self.current_pos

        target_pos = self.turret_target
        if target_pos is not None and env_map.tile(target_pos.x, target_pos.y) & (1 << WALL):
            self.turret_target = None
            target_pos = None

        if target_pos is None:
            best_dist = float("inf")
            my_id = c.get_id()

            # Find enemy logistics that feed directly into the enemy core.
            for eid in c.get_nearby_entities():
                if c.get_team(eid) == c.get_team():
                    continue
                etype = c.get_entity_type(eid)
                if etype not in (EntityType.CONVEYOR, EntityType.BRIDGE):
                    continue

                pos = c.get_position(eid)

                # Skip tiles occupied by another friendly builder — they're
                # already working on it and we'd just block each other.
                occupant = c.get_tile_builder_bot_id(pos)
                if occupant is not None and occupant != my_id:
                    continue

                if etype == EntityType.BRIDGE:
                    # Bridges jump resources to a distant tile — check whether
                    # the bridge target lands near the enemy core, not the bridge
                    # position itself (which can be anywhere in sensor range).
                    bridge_target = c.get_bridge_target(eid)
                    if bridge_target is None:
                        continue
                    dx = abs(bridge_target.x - enemy_pos.x)
                    dy = abs(bridge_target.y - enemy_pos.y)
                else:
                    dx = abs(pos.x - enemy_pos.x)
                    dy = abs(pos.y - enemy_pos.y)

                if max(dx, dy) != 2 or (dx == 2 and dy == 2):
                    continue
                dist = pos.distance_squared(enemy_pos)
                if dist < best_dist:
                    best_dist = dist
                    target_pos = pos

        if target_pos is not None:
            self.target_pos = target_pos
            dist_sq = me.distance_squared(target_pos)

            if me == target_pos:
                building_id = c.get_tile_building_id(target_pos)
                # If the tile is still occupied by enemy infrastructure, blow it up first.
                if building_id is not None and c.get_team(building_id) != c.get_team():
                    if c.can_fire(target_pos):
                        c.fire(target_pos)
                        self.turret_target = target_pos
                    return

                self.turret_target = target_pos

                # Step off the target tile so we can replace it with a gunner
                retreat_dir = enemy_pos.direction_to(self.core_pos)
                retreat_pos = me.add(retreat_dir)
                # Back away from the enemy core
                if c.can_move(retreat_dir):
                    c.move(retreat_dir)
                    return
                # If blocked, make a retreat tile for the next turn
                if c.get_action_cooldown() == 0 and c.can_build_road(retreat_pos):
                    c.build_road(retreat_pos)
                    return
                # Otherwise, take any move that still keeps us in build range
                for direction in Direction:
                    if direction == Direction.CENTRE:
                        continue
                    next_pos = me.add(direction)
                    if next_pos.distance_squared(target_pos) > 2:
                        continue
                    if c.can_move(direction):
                        c.move(direction)
                        return
                return

            if dist_sq <= 2:
                building_id = c.get_tile_building_id(target_pos)

                # Clear an allied road that's blocking the gunner placement.
                if (
                    building_id is not None
                    and me != target_pos
                    and c.get_entity_type(building_id) == EntityType.ROAD
                    and c.get_team(building_id) == c.get_team()
                    and c.can_destroy(target_pos)
                ):
                    c.destroy(target_pos)
                    return

                # Once the tile is clear, build a gunner facing the enemy core.
                if building_id is None and me != target_pos:
                    facing = target_pos.direction_to(enemy_pos)
                    if c.can_build_gunner(target_pos, facing):
                        c.build_gunner(target_pos, facing)
                        self.gunners_placed += 1
                        self.turret_target = None
                    return

            self._search(c, target_pos)
            return

        self.target_pos = enemy_pos
        self._search(c, enemy_pos)

    def _done(self, c: Controller):
        """TODO: Heal gunners & Supply ammo"""
        pass

    def _draw_debug(self, c: Controller):
        """Draw state-based dot and target line for debugging"""
        # State colors: NAVIGATE=green, PLACE_SELF_DESTRUCT=red, DONE=gray
        state_colors = {
            AttackState.NAVIGATE: (0, 255, 0),
            AttackState.PLACE_SELF_DESTRUCT: (255, 0, 0),
            AttackState.DONE: (128, 128, 128),
        }
        r, g, b = state_colors.get(self.state, (255, 255, 255))
        c.draw_indicator_dot(self.current_pos, r, g, b)

        # Draw line to current navigation target
        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, r, g, b)

    def run(self, c: Controller):
        # Initialise (or update) the environment map
        if self._env_map is None:
            self._env_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        self._env_map.update(c)

        # Calculate enemy core candidates once
        if len(self.enemy_core_candidates) == 0:
            cx, cy = self.core_pos.x, self.core_pos.y
            W, H = c.get_map_width(), c.get_map_height()
            self.enemy_core_candidates = [
                Position(W - 1 - cx, H - 1 - cy),  # Rotational (180°) — default assumption
                Position(W - 1 - cx, cy),  # Horizontal reflection
                Position(cx, H - 1 - cy),  # Vertical reflection
            ]
            self.enemy_core_candidate_idx = 0  # assume rotational (180°) by default

        # Once symmetry is resolved, jump to the matching candidate
        if self.enemy_pos is None and self._env_map.symmetry_resolved:
            _sym_idx = {Symmetry.ROTATIONAL: 0, Symmetry.HORIZONTAL: 1, Symmetry.VERTICAL: 2}
            sym = self._env_map.symmetry
            new_idx = _sym_idx.get(sym, 0) if sym is not None else 0
            if new_idx != self.enemy_core_candidate_idx:
                self.enemy_core_candidate_idx = new_idx
                self._planner_goal = None  # force replanning to new target

        # TODO: Use markers to broadcast confirmed enemy position to other builders

        # Check we are targetting correct enemy core
        if self.enemy_pos is None:
            for eid in c.get_nearby_buildings():
                if (
                    c.get_entity_type(eid) == EntityType.CORE
                    and c.get_team(eid) != c.get_team()
                ):
                    self.enemy_pos = c.get_position(eid)
                    # Navigates to two tiles outside the enemy core
                    approach = self.core_pos.direction_to(self.enemy_pos)
                    adx, ady = approach.delta()
                    self.attack_target = Position(
                        self.enemy_pos.x - adx * 2,
                        self.enemy_pos.y - ady * 2,
                    )
                    self._planner_goal = None  # force replanning to attack target
                    break

        self.current_pos = c.get_position()

        match self.state:
            case AttackState.NAVIGATE:
                self._navigate(c)
            case AttackState.PLACE_SELF_DESTRUCT:
                self._place_self_destruct(c)
            case AttackState.DONE:
                self._done(c)

        # self._draw_debug(c)