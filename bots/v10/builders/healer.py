from cambc import Controller, Direction, EntityType, Position

from utils.d_star import DStarLite
from utils.raw_map_representation import EnvironmentMap, WALL


# Clockwise ordering of the eight tiles surrounding the core, starting at EAST
# — the spawn offset for the healer (see BuilderType.HEALER).
_RING_DIRECTIONS = [
    Direction.EAST,
    Direction.SOUTHEAST,
    Direction.SOUTH,
    Direction.SOUTHWEST,
    Direction.WEST,
    Direction.NORTHWEST,
    Direction.NORTH,
    Direction.NORTHEAST,
]

# Buildings a builder bot may stand on. Everything else (turrets, harvesters,
# foundries, barriers, enemy cores) must be routed around.
_WALKABLE_BUILDINGS = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
        EntityType.ROAD,
    }
)

# Building types we remember and repair if destroyed on the perimeter. Skips
# CORE (un-rebuildable), MARKER, and BUILDER_BOT.
_TRACKED_TYPES = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
        EntityType.ROAD,
        EntityType.HARVESTER,
        EntityType.FOUNDRY,
        EntityType.BARRIER,
        EntityType.GUNNER,
        EntityType.SENTINEL,
        EntityType.BREACH,
        EntityType.LAUNCHER,
    }
)

# Types where `get_direction` is defined.
_DIRECTIONAL_TYPES = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.SPLITTER,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.GUNNER,
        EntityType.SENTINEL,
        EntityType.BREACH,
    }
)

# Only walls block healer navigation — other tiles are walkable or handled as
# dynamic blockers.
_REPAIR_BLOCK_MASK = (1 << WALL)


class Healer:
    def __init__(self, core_pos: Position):
        self.core_pos = core_pos
        self.core_id: int | None = None
        self.ring_idx = 0

        self._env_map: EnvironmentMap | None = None
        self._planner: DStarLite | None = None
        self._planner_goal: tuple[int, int] | None = None
        self._repair_target: Position | None = None
        # Last observed allied building signature per perimeter tile.
        # extra is Direction for directional, Position for bridges, None otherwise.
        self._remembered: dict[
            tuple[int, int], tuple[EntityType, Direction | Position | None]
        ] = {}
        self._perimeter_tiles: list[Position] | None = None

    def _ring_pos(self, idx: int) -> Position:
        return self.core_pos.add(_RING_DIRECTIONS[idx % len(_RING_DIRECTIONS)])

    def _resolve_core_id(self, c: Controller) -> None:
        bid = c.get_tile_building_id(self.core_pos)
        if bid is not None and c.get_entity_type(bid) == EntityType.CORE:
            self.core_id = bid

    def _align_ring_idx(self, c: Controller) -> None:
        me = c.get_position()
        offset = (me.x - self.core_pos.x, me.y - self.core_pos.y)
        for i, d in enumerate(_RING_DIRECTIONS):
            if d.delta() == offset:
                self.ring_idx = i
                return

    def _core_damaged(self, c: Controller) -> bool:
        if self.core_id is None:
            return False
        return c.get_hp(self.core_id) < c.get_max_hp(self.core_id)

    def _compute_perimeter(self, c: Controller) -> list[Position]:
        """Tiles at Chebyshev distance 2 from the core — the 5x5 perimeter."""
        tiles: list[Position] = []
        cx, cy = self.core_pos.x, self.core_pos.y
        w, h = c.get_map_width(), c.get_map_height()
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if max(abs(dx), abs(dy)) != 2:
                    continue
                x, y = cx + dx, cy + dy
                if 0 <= x < w and 0 <= y < h:
                    tiles.append(Position(x, y))
        return tiles

    def _search(self, c: Controller, target: Position) -> None:
        """Navigate towards target with D* Lite, paving empty tiles along the way."""
        if c.get_move_cooldown() > 0:
            return

        env_map = self._env_map
        assert env_map is not None
        pos = c.get_position()
        goal = (target.x, target.y)
        if self._planner is None or self._planner_goal != goal:
            self._planner = DStarLite(
                env_map, target.x, target.y, block_mask=_REPAIR_BLOCK_MASK
            )
            self._planner_goal = goal

        my_id = c.get_id()
        my_team = c.get_team()
        blockers: list[tuple[int, int]] = []
        for p in c.get_nearby_tiles():
            bot_id = c.get_tile_builder_bot_id(p)
            if bot_id is not None and bot_id != my_id:
                blockers.append((p.x, p.y))
                continue
            bld_id = c.get_tile_building_id(p)
            if bld_id is None:
                continue
            etype = c.get_entity_type(bld_id)
            if etype == EntityType.CORE:
                if c.get_team(bld_id) != my_team:
                    blockers.append((p.x, p.y))
                continue
            if etype not in _WALKABLE_BUILDINGS:
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

    def _building_signature(
        self, c: Controller, bid: int
    ) -> tuple[EntityType, Direction | Position | None] | None:
        etype = c.get_entity_type(bid)
        if etype not in _TRACKED_TYPES:
            return None
        if etype in _DIRECTIONAL_TYPES:
            return etype, c.get_direction(bid)
        if etype == EntityType.BRIDGE:
            return etype, c.get_bridge_target(bid)
        return etype, None

    def _update_memory(self, c: Controller) -> None:
        """Refresh _remembered with whatever allied building sits on each perimeter tile."""
        my_team = c.get_team()
        for pos in self._perimeter_tiles or ():
            bid = c.get_tile_building_id(pos)
            if bid is None or c.get_team(bid) != my_team:
                continue
            sig = self._building_signature(c, bid)
            if sig is not None:
                self._remembered[(pos.x, pos.y)] = sig

    def _pick_build_target(
        self, c: Controller
    ) -> tuple[Position, EntityType, Direction | Position | None] | None:
        """Nearest empty perimeter tile needing a build.

        Priority:
        1. Tiles we've remembered an allied building on — rebuild that exact type.
        2. Otherwise, drop a launcher to saturate the perimeter with launchers.
        """
        me = c.get_position()
        best_repair: Position | None = None
        best_repair_d = float("inf")
        best_new: Position | None = None
        best_new_d = float("inf")

        for pos in self._perimeter_tiles or ():
            if c.get_tile_building_id(pos) is not None:
                continue
            d = me.distance_squared(pos)
            key = (pos.x, pos.y)
            if key in self._remembered:
                if d < best_repair_d:
                    best_repair_d = d
                    best_repair = pos
            elif d < best_new_d:
                best_new_d = d
                best_new = pos

        if best_repair is not None:
            etype, extra = self._remembered[(best_repair.x, best_repair.y)]
            return best_repair, etype, extra
        if best_new is not None:
            return best_new, EntityType.LAUNCHER, None
        return None

    def _try_build(
        self,
        c: Controller,
        target: Position,
        etype: EntityType,
        extra: Direction | Position | None,
    ) -> bool:
        if c.get_tile_building_id(target) is not None:
            return False
        if not c.can_build(etype, target, extra):
            return False
        c.build(etype, target, extra)
        return True

    def _step_off(self, c: Controller, target: Position) -> bool:
        """Move off target while keeping within action radius. Returns True if moved."""
        me = c.get_position()
        primary = me.direction_to(self.core_pos)
        if primary != Direction.CENTRE and c.can_move(primary):
            c.move(primary)
            return True
        for d in Direction:
            if d == Direction.CENTRE:
                continue
            nxt = me.add(d)
            if nxt.distance_squared(target) > 2:
                continue
            if c.can_move(d):
                c.move(d)
                return True
        return False

    def _repair(self, c: Controller) -> bool:
        """Rebuild destroyed perimeter buildings and saturate empty tiles with launchers.

        Returns True if the healer took a build-related action this turn.
        """
        self._update_memory(c)

        plan = self._pick_build_target(c)
        if plan is None:
            self._repair_target = None
            return False

        target, etype, extra = plan

        # Reset the planner when the target changes so D* Lite replans from scratch.
        if self._repair_target != target:
            self._repair_target = target
            self._planner_goal = None

        me = c.get_position()

        # If out of action radius, step closer first. After _search we may
        # now be within range (or standing on target), so re-check below.
        if me != target and me.distance_squared(target) > 2:
            self._search(c, target)
            me = c.get_position()

        if me == target:
            # Walkable types (conveyor, road, …) can be built on our own tile.
            if self._try_build(c, target, etype, extra):
                self._repair_target = None
                return True
            # Otherwise step off and try again next turn.
            self._step_off(c, target)
            return True

        if me.distance_squared(target) <= 2:
            if self._try_build(c, target, etype, extra):
                self._repair_target = None

        return True

    def _patrol(self, c: Controller) -> None:
        if c.get_move_cooldown() > 0:
            return

        me = c.get_position()

        # Prefer stepping one tile clockwise; fall back to step=2 (still
        # adjacent on diagonals) so a permanently-blocked tile can be skipped.
        for step in (1, 2):
            next_idx = (self.ring_idx + step) % len(_RING_DIRECTIONS)
            next_pos = self._ring_pos(next_idx)
            if me.distance_squared(next_pos) > 2:
                continue
            direction = me.direction_to(next_pos)
            if direction == Direction.CENTRE:
                continue
            if c.can_move(direction):
                c.move(direction)
                self.ring_idx = next_idx
                return

        # Nothing walkable ahead — pave the immediate next tile so we can
        # cross it next turn.
        forward_pos = self._ring_pos(self.ring_idx + 1)
        if c.get_action_cooldown() == 0 and c.can_build_road(forward_pos):
            c.build_road(forward_pos)

    def run(self, c: Controller):
        if self.core_id is None:
            self._resolve_core_id(c)
        if self._env_map is None:
            self._env_map = EnvironmentMap(c.get_map_width(), c.get_map_height())
        self._env_map.update(c)
        if self._perimeter_tiles is None:
            self._perimeter_tiles = self._compute_perimeter(c)

        if self._repair(c):
            return

        me = c.get_position()
        if me.distance_squared(self.core_pos) > 2:
            # Drifted off the ring during a repair trip — head home.
            self._search(c, self.core_pos)
            return

        self._align_ring_idx(c)

        if self._core_damaged(c) and c.can_heal(self.core_pos):
            c.heal(self.core_pos)
            return

        self._patrol(c)
