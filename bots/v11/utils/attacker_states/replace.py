from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType

from utils.attacker_states.state import AttackState

if TYPE_CHECKING:
    from builders.attacker import Attacker


_STEP_OFF = (
    Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
    Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST,
)

# Only the band gunner < d² <= sentinel needs the pricier sentinel.
_SENTINEL_ATTACK_RADIUS_SQ = 32
_GUNNER_ATTACK_RADIUS_SQ = 9


def _execute_replacement(self: Attacker, c: Controller) -> bool:
    """Attack, step off, drop a turret on the same tile we attacked."""
    target = self.target_conveyor
    assert target is not None
    me = self.current_pos
    my_team = c.get_team()

    bld_id = c.get_tile_building_id(target)
    team = c.get_team(bld_id) if bld_id is not None else None
    etype = c.get_entity_type(bld_id) if bld_id is not None else None

    match (team, etype):
        case (t, EntityType.SENTINEL | EntityType.GUNNER) if t == my_team:
            self.sentinels_placed += 1
            return True
        case (t, _) if t is not None and t != my_team:
            # Enemy on target: walk on (conveyor is walkable) and own-tile fire.
            if me == target:
                key = (target.x, target.y)
                if self._attack_target_key != key:
                    self._attack_target_key = key
                    self._attack_turns = 0
                    self._attack_max_hp = c.get_max_hp(bld_id)
                self._attack_turns += 1
                if self._attack_turns > 10 and c.get_hp(bld_id) * 2 >= self._attack_max_hp:
                    self.blacklist[key] = c.get_current_round()
                    return True
                if c.can_fire(me):
                    c.fire(me)
            elif c.can_move(me.direction_to(target)):
                c.move(me.direction_to(target))
            return False
        case (t, EntityType.ROAD) if t == my_team:
            our_road = True
        case (None, _) | (_, None):
            our_road = False
        case _:
            # Friendly stray (not road, not turret) — tear it down.
            if c.can_destroy(target):
                c.destroy(target)
            return False

    # Step off (move cd is separate from action cd, so the build below chains).
    if me == target:
        step = next((d for d in _STEP_OFF if c.can_move(d)), None)
        if step is None:
            self.blacklist[(target.x, target.y)] = c.get_current_round()
            return True
        c.move(step)
        me = c.get_position()

    facing = me.direction_to(target)
    if self.enemy_core_pos is not None:
        d = target.direction_to(self.enemy_core_pos)
        if d != Direction.CENTRE:
            facing = d

    ti = c.get_global_resources()[0]

    ec = self.enemy_core_pos
    if ec is not None:
        d2 = target.distance_squared(ec)
        use_gunner = d2 > _SENTINEL_ATTACK_RADIUS_SQ or d2 <= _GUNNER_ATTACK_RADIUS_SQ
    else:
        use_gunner = False
    turret_cost, can_build_turret, build_turret = (
        (c.get_gunner_cost()[0], c.can_build_gunner, c.build_gunner)
        if use_gunner else
        (c.get_sentinel_cost()[0], c.can_build_sentinel, c.build_sentinel)
    )

    if our_road:
        # Upgrade the road to a turret once Ti lands.
        if ti >= turret_cost and c.can_destroy(target):
            c.destroy(target)
            if can_build_turret(target, facing):
                build_turret(target, facing)
                self.sentinels_placed += 1
                return True
        return False

    # Empty target: turret if affordable, else a 1-Ti road to reserve.
    if ti >= turret_cost and can_build_turret(target, facing):
        build_turret(target, facing)
        self.sentinels_placed += 1
        return True
    if c.can_build_road(target):
        c.build_road(target)
    return False


def _target_still_valid(self: Attacker, c: Controller) -> bool:
    target = self.target_conveyor
    if target is None:
        return False
    if not c.is_in_vision(target):
        return True
    bld_id = c.get_tile_building_id(target)
    if bld_id is None:
        return True
    et = c.get_entity_type(bld_id)
    if c.get_team(bld_id) == c.get_team():
        return et in (EntityType.SENTINEL, EntityType.GUNNER, EntityType.ROAD)
    return et in (EntityType.CONVEYOR, EntityType.BRIDGE)


def _replace(self: Attacker, c: Controller) -> None:
    if _execute_replacement(self, c):
        self.target_conveyor = None
        self._planner_goal = None
        self.state = AttackState.SCAN
