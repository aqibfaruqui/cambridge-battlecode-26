from enum import Enum

from cambc import Controller, Direction, EntityType, Position

from utils.healer_states.defend import _defend_healer
from utils.healer_states.follow import _follow, _try_enter_follow


class HealState(Enum):
    __slots__ = ()

    PATROL = "patrol"
    FOLLOW = "follow"
    DEFEND = "defend"


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

        self.state = HealState.PATROL
        self.current_pos = Position(0, 0)
        self.ti = 0
        self.ax = 0

        self.follow_enemy_id: int | None = None
        self.defend_enemy_id: int | None = None
        self.defend_target_tile: Position | None = None
        self.defend_gunner_pos: Position | None = None
        self.defend_orig_conveyor_dir: Direction | None = None
        self.enemy_tile_hp: dict[tuple[int, int], int] = {}

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
        try:
            hp = c.get_hp(self.core_id)
            max_hp = c.get_max_hp(self.core_id)
            return hp < max_hp
        except Exception:
            return False

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
        """Heal the lowest-HP allied conveyor within action radius 2."""
        if c.get_action_cooldown() > 0:
            return False
        me = c.get_position()
        my_team = c.get_team()
        w, h = c.get_map_width(), c.get_map_height()
        best: Position | None = None
        best_hp = float("inf")
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
                if hp < best_hp:
                    best_hp = hp
                    best = p
        if best is None:
            return False
        c.heal(best)
        return True

    def _patrol(self, c: Controller) -> None:
        if c.get_move_cooldown() > 0:
            return

        me = c.get_position()

        step1_idx = (self.ring_idx + 1) % len(_RING_DIRECTIONS)
        step1_pos = self._ring_pos(step1_idx)

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

        # Another builder bot is parked on the next tile — detour through
        # the core (centre of the 3x3) and resume at the square past the
        # blocker on the following tick.
        if c.get_tile_builder_bot_id(step1_pos) is not None:
            direction = me.direction_to(self.core_pos)
            if direction != Direction.CENTRE and c.can_move(direction):
                c.move(direction)
                self.ring_idx = step1_idx
                return

        # Nothing walkable ahead — pave the immediate next tile so we can
        # cross it next turn.
        if c.get_action_cooldown() == 0 and c.can_build_road(step1_pos):
            c.build_road(step1_pos)

    def _run_patrol(self, c: Controller, took_damage: bool) -> None:
        # Try to acquire a target. If we do, the state change takes effect
        # next turn; this turn we still heal + walk the ring.
        _try_enter_follow(self, c)

        healed = False
        if self._try_heal_self(c):
            healed = True
        elif self._try_heal_core(c) or self._try_heal_conveyor(c):
            healed = True

        if took_damage or not healed:
            self._patrol(c)

    def run(self, c: Controller):
        if self.core_id is None:
            self._resolve_core_id(c)

        self.current_pos = c.get_position()
        self.ti, self.ax = c.get_global_resources()
        self._align_ring_idx(c)

        my_id = c.get_id()
        hp_now = c.get_hp(my_id)
        took_damage = self._last_hp is not None and hp_now < self._last_hp

        match self.state:
            case HealState.PATROL:
                self._run_patrol(c, took_damage)
            case HealState.FOLLOW:
                _follow(self, c)
            case HealState.DEFEND:
                _defend_healer(self, c)

        self._last_hp = c.get_hp(my_id)
