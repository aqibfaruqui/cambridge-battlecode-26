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

        if self._core_damaged(c) and c.can_heal(self.core_pos):
            c.heal(self.core_pos)
            return

        self._patrol(c)
