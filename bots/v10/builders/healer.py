from cambc import Controller, Direction, EntityType, Position


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


class Healer:
    def __init__(self, core_pos: Position):
        self.core_pos = core_pos
        self.core_id: int | None = None
        self.ring_idx = 0
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

    def _has_adjacent_launcher(self, c: Controller, pos: Position) -> bool:
        w, h = c.get_map_width(), c.get_map_height()
        for d in Direction:
            if d == Direction.CENTRE:
                continue
            n = pos.add(d)
            if not (0 <= n.x < w and 0 <= n.y < h):
                continue
            if not c.is_in_vision(n):
                continue
            bid = c.get_tile_building_id(n)
            if bid is None:
                continue
            if c.get_entity_type(bid) == EntityType.LAUNCHER:
                return True
        return False

    def _try_place_launcher(self, c: Controller) -> bool:
        """Place a launcher on the nearest empty / own-road perimeter tile in action range."""
        if c.get_action_cooldown() > 0:
            return False
        me = c.get_position()
        my_team = c.get_team()
        best: Position | None = None
        best_d = float("inf")
        for pos in self._perimeter_tiles or ():
            d = me.distance_squared(pos)
            if d > 2:
                continue
            if not c.is_in_vision(pos):
                continue
            bid = c.get_tile_building_id(pos)
            if bid is not None:
                if c.get_team(bid) != my_team:
                    continue
                if c.get_entity_type(bid) != EntityType.ROAD:
                    continue
            if self._has_adjacent_launcher(c, pos):
                continue
            if d < best_d:
                best_d = d
                best = pos
        if best is None:
            return False
        if c.get_tile_building_id(best) is not None:
            # Clear our own road so we can upgrade the tile. Destroy is free of
            # action cooldown, so we can still build the launcher this turn.
            if not c.can_destroy(best):
                return False
            c.destroy(best)
        if not c.can_build(EntityType.LAUNCHER, best, None):
            return False
        c.build(EntityType.LAUNCHER, best, None)
        return True

    def _try_heal_core(self, c: Controller) -> bool:
        if not self._core_damaged(c):
            return False
        if not c.can_heal(self.core_pos):
            return False
        c.heal(self.core_pos)
        return True

    def _try_heal_conveyor(self, c: Controller) -> bool:
        """Heal the most-damaged allied conveyor within action radius 2."""
        if c.get_action_cooldown() > 0:
            return False
        me = c.get_position()
        my_team = c.get_team()
        w, h = c.get_map_width(), c.get_map_height()
        best: Position | None = None
        best_ratio = float("inf")
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                x, y = me.x + dx, me.y + dy
                if not (0 <= x < w and 0 <= y < h):
                    continue
                p = Position(x, y)
                if not c.is_in_vision(p):
                    continue
                bid = c.get_tile_building_id(p)
                if bid is None:
                    continue
                if c.get_team(bid) != my_team:
                    continue
                if c.get_entity_type(bid) != EntityType.CONVEYOR:
                    continue
                max_hp = c.get_max_hp(bid)
                hp = c.get_hp(bid)
                if hp >= max_hp:
                    continue
                if not c.can_heal(p):
                    continue
                ratio = hp / max_hp
                if ratio < best_ratio:
                    best_ratio = ratio
                    best = p
        if best is None:
            return False
        c.heal(best)
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
        if self._perimeter_tiles is None:
            self._perimeter_tiles = self._compute_perimeter(c)

        self._align_ring_idx(c)

        if not self._try_place_launcher(c):
            if not self._try_heal_core(c):
                self._try_heal_conveyor(c)

        self._patrol(c)
