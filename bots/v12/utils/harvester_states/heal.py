from __future__ import annotations
import sys
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position

from utils.harvester_states.seek import _seek_direction

if TYPE_CHECKING:
    from builders.harvester import Harvester


_HEAL_THRESHOLD = 0.8

_HEALABLE_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.CORE,
    EntityType.HARVESTER,
    EntityType.SPLITTER,
    EntityType.FOUNDRY,
})

_TYPE_PRIORITY = {
    EntityType.CORE: 0,
    EntityType.HARVESTER: 1,
    EntityType.SPLITTER: 2,
    EntityType.FOUNDRY: 3,
    EntityType.BRIDGE: 4,
    EntityType.CONVEYOR: 5,
}


def _critical_damaged(c: Controller) -> list[Position]:
    """Allied buildings below threshold, sorted by type priority then HP ratio."""
    my_team = c.get_team()
    hits: list[tuple[int, float, Position]] = []
    for bid in c.get_nearby_buildings():
        if c.get_team(bid) != my_team:
            continue
        if c.get_entity_type(bid) not in _HEALABLE_TYPES:
            continue
        hp = c.get_hp(bid)
        max_hp = c.get_max_hp(bid)
        ratio = hp / max_hp
        if ratio >= _HEAL_THRESHOLD:
            continue
        prio = _TYPE_PRIORITY.get(c.get_entity_type(bid), 99)
        hits.append((prio, ratio, c.get_position(bid)))
    hits.sort(key=lambda x: (x[0], x[1]))
    return [pos for _, _, pos in hits]


def _find_attacker(c: Controller, targets: list[Position]) -> Position | None:
    """Enemy unit closest to any position in targets."""
    my_team = c.get_team()
    best: Position | None = None
    best_d = float("inf")
    for uid in c.get_nearby_units():
        if c.get_team(uid) == my_team:
            continue
        epos = c.get_position(uid)
        d = min(epos.distance_squared(t) for t in targets)
        if d < best_d:
            best_d = d
            best = epos
    return best


def _approach_tile(c: Controller, me: Position, target: Position) -> Position:
    """Closest tile within heal range (d² ≤ 2) of target, so D* Lite gets a walkable goal."""
    w, h = c.get_map_width(), c.get_map_height()
    best = target
    best_d = float("inf")
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            cx, cy = target.x + dx, target.y + dy
            if not (0 <= cx < w and 0 <= cy < h):
                continue
            d = me.distance_squared(Position(cx, cy))
            if d < best_d:
                best_d = d
                best = Position(cx, cy)
    return best


def _best_coverage_tile(c: Controller, me: Position, damaged: list[Position]) -> Position:
    """Tile adjacent to any damaged building that maximises the count of damaged buildings
    reachable from it within heal range (d² ≤ 2). Tiebreak: closest to bot."""
    w, h = c.get_map_width(), c.get_map_height()
    best_pos: Position | None = None
    best_score = -1
    best_dist = float("inf")
    for target in damaged:
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                cx, cy = target.x + dx, target.y + dy
                if not (0 <= cx < w and 0 <= cy < h):
                    continue
                cand = Position(cx, cy)
                score = sum(1 for p in damaged if cand.distance_squared(p) <= 2)
                dist = me.distance_squared(cand)
                if score > best_score or (score == best_score and dist < best_dist):
                    best_score, best_pos, best_dist = score, cand, dist
    return best_pos if best_pos is not None else damaged[0]


def _all_allied_buildings(c: Controller) -> list[Position]:
    my_team = c.get_team()
    return [
        c.get_position(bid)
        for bid in c.get_nearby_buildings()
        if c.get_team(bid) == my_team
        and c.get_entity_type(bid) in _HEALABLE_TYPES
    ]


def _enemy_count_near(c: Controller, pos: Position, my_team) -> int:
    """Enemies within attack range (~3 tiles) of pos — sets how many healers can pile on."""
    count = sum(
        1 for uid in c.get_nearby_units()
        if c.get_team(uid) != my_team and pos.distance_squared(c.get_position(uid)) <= 9
    )
    return max(1, count)


def _claim_target(self: Harvester, c: Controller, damaged: list[Position]) -> Position | None:
    """
    Claim the highest-priority damaged building where this bot is among the N closest
    allied bots, with N = number of enemies attacking that building. This lets multiple
    healers converge on a single building when it's under heavy attack.
    """
    my_team = c.get_team()
    for focus in damaged:
        max_healers = _enemy_count_near(c, focus, my_team)
        my_d = self.current_pos.distance_squared(focus)
        closer_count = 0
        for uid in c.get_nearby_units():
            if c.get_team(uid) != my_team:
                continue
            if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
                continue
            if c.get_position(uid) == self.current_pos:
                continue
            other_d = c.get_position(uid).distance_squared(focus)
            if other_d < my_d or (other_d == my_d and uid < c.get_id()):
                closer_count += 1
        if closer_count < max_healers:
            return focus
    return None


def _try_enter_heal(self: Harvester, c: Controller) -> bool:
    from builders.harvester import HarvestState

    damaged = _critical_damaged(c)
    if not damaged:
        return False

    target = _claim_target(self, c, damaged)
    if target is None:
        return False

    self.heal_prev_state = self.state
    self.heal_interrupt_target = target
    self.state = HarvestState.HEAL
    return True


def _heal(self: Harvester, c: Controller) -> None:
    from builders.harvester import HarvestState

    damaged = _critical_damaged(c)

    # Re-validate committed target each turn.
    committed = self.heal_interrupt_target
    if committed is not None and c.is_in_vision(committed):
        bid = c.get_tile_building_id(committed)
        if (
            bid is None
            or c.get_team(bid) != c.get_team()
            or c.get_hp(bid) / c.get_max_hp(bid) >= _HEAL_THRESHOLD
        ):
            committed = None

    # Try to claim a new target if we lost ours.
    if committed is None and damaged:
        committed = _claim_target(self, c, damaged)
    self.heal_interrupt_target = committed

    # Track idle turns (no committed target). Exit after 8 idle turns —
    # attacker is present but not actually damaging anything.
    _IDLE_EXIT_TURNS = 8
    if committed is None:
        self.heal_idle_turns += 1
    else:
        self.heal_idle_turns = 0

    all_buildings = _all_allied_buildings(c)
    attacker = _find_attacker(c, damaged if damaged else all_buildings)
    if committed is None and (attacker is None or self.heal_idle_turns >= _IDLE_EXIT_TURNS):
        self.state = self.heal_prev_state if self.heal_prev_state is not None else HarvestState.SEEK
        self.heal_prev_state = None
        self.heal_interrupt_target = None
        self.heal_idle_turns = 0
        return

    me = self.current_pos

    # Heal the highest-priority damaged tile currently in range.
    if c.get_action_cooldown() == 0:
        for pos in damaged:
            if me.distance_squared(pos) <= 2 and c.can_heal(pos):
                c.heal(pos)
                break

    # Navigate to the tile that covers the most damaged buildings simultaneously.
    # Falls back to the committed building when nothing is actively damaged.
    dest = None
    if c.get_move_cooldown() == 0:
        if damaged:
            approach = _best_coverage_tile(c, me, damaged)
        elif committed is not None:
            approach = _approach_tile(c, me, committed)
        else:
            approach = None
        dest = approach
        if approach is not None and me.distance_squared(approach) > 0:
            move_dir = _seek_direction(self, c, approach)
            if move_dir is None:
                from utils.defense.combat import step_toward
                step_toward(c, me, approach)
            else:
                self._advance(c, move_dir)

    attacker_str = f"({attacker.x},{attacker.y})" if attacker is not None else "-"
    committed_str = f"({committed.x},{committed.y})" if committed is not None else "-"
    damaged_str = ",".join(f"({p.x},{p.y})" for p in damaged[:3]) or "-"
    dest_str = f"({dest.x},{dest.y})" if dest is not None else "-"
    print(
        f"[heal {c.get_id()}] r={c.get_current_round()} "
        f"pos=({me.x},{me.y}) "
        f"attacker={attacker_str} "
        f"committed={committed_str} "
        f"dest={dest_str} "
        f"damaged=[{damaged_str}] "
        f"acd={c.get_action_cooldown()} mcd={c.get_move_cooldown()}",
        file=sys.stderr,
    )
