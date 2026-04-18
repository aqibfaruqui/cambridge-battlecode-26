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
        self._last_hp: int | None = None

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

    def _find_core_adjacent_enemy(self, c: Controller) -> Position | None:
        """Return the position of an enemy builder bot on the 8-tile ring, if any."""
        my_team = c.get_team()
        for d in _RING_DIRECTIONS:
            p = self.core_pos.add(d)
            if not c.is_in_vision(p):
                continue
            bot_id = c.get_tile_builder_bot_id(p)
            if bot_id is None:
                continue
            if c.get_team(bot_id) != my_team:
                return p
        return None

    def _try_place_launcher(self, c: Controller) -> bool:
        """Reactively drop a launcher near an enemy builder bot sitting on the ring."""
        if c.get_action_cooldown() > 0:
            return False
        enemy_pos = self._find_core_adjacent_enemy(c)
        if enemy_pos is None:
            return False

        me = c.get_position()
        my_team = c.get_team()
        w, h = c.get_map_width(), c.get_map_height()
        best: Position | None = None
        best_d = float("inf")
        # Any tile within Chebyshev 2 of the enemy that we can reach this turn.
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if dx == 0 and dy == 0:
                    continue
                x, y = enemy_pos.x + dx, enemy_pos.y + dy
                if not (0 <= x < w and 0 <= y < h):
                    continue
                p = Position(x, y)
                if p == self.core_pos:
                    continue
                d = me.distance_squared(p)
                if d > 2:
                    continue
                if not c.is_in_vision(p):
                    continue
                bid = c.get_tile_building_id(p)
                if bid is not None:
                    if c.get_team(bid) != my_team:
                        continue
                    if c.get_entity_type(bid) != EntityType.ROAD:
                        continue
                if d < best_d:
                    best_d = d
                    best = p
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

    def _try_heal_self(self, c: Controller) -> bool:
        if c.get_action_cooldown() > 0:
            return False
        my_id = c.get_id()
        if c.get_hp(my_id) >= c.get_max_hp(my_id):
            return False
        me = c.get_position()
        if not c.can_heal(me):
            return False
        c.heal(me)
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

        self._align_ring_idx(c)

        my_id = c.get_id()
        hp_now = c.get_hp(my_id)
        took_damage = self._last_hp is not None and hp_now < self._last_hp

        healed = False
        if self._try_heal_self(c):
            healed = True
        elif not self._try_place_launcher(c):
            if self._try_heal_core(c) or self._try_heal_conveyor(c):
                healed = True

        # Hold position while healing a stable situation — only move if we
        # didn't heal, or if we took damage since last turn.
        if took_damage or not healed:
            self._patrol(c)

        self._last_hp = c.get_hp(my_id)
