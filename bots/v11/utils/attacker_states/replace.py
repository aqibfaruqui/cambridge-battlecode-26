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

# Attack r² for each turret (same as its vision r²). Outside the sentinel's
# range the sentinel can't hit the core anyway, and inside the gunner's range
# both can reach it — either way the cheaper gunner is the right pick. Only
# the in-between band (gunner < d² <= sentinel) warrants the pricier sentinel.
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

    # Turret already placed — done.
    if team == my_team and etype in (EntityType.SENTINEL, EntityType.GUNNER):
        self.sentinels_placed += 1
        return True

    # Enemy on target: walk on (conveyor is walkable) and own-tile fire.
    if bld_id is not None and team != my_team:
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

    # Friendly stray that isn't our road reservation — tear it down.
    our_road = team == my_team and etype == EntityType.ROAD
    if bld_id is not None and not our_road:
        if c.can_destroy(target):
            c.destroy(target)
        return False

    # Step off the target. Move cooldown is separate from action cooldown,
    # so the build below chains into the same tick.
    if me == target:
        for d in _STEP_OFF:
            if c.can_move(d):
                c.move(d)
                me = c.get_position()
                break
        else:
            self.blacklist[(target.x, target.y)] = c.get_current_round()
            return True

    facing = me.direction_to(target)
    if self.enemy_core_pos is not None:
        d = target.direction_to(self.enemy_core_pos)
        if d != Direction.CENTRE:
            facing = d

    ti = c.get_global_resources()[0]

    # Gunner wins outside the sentinel's range (sentinel can't reach anyway)
    # and inside the gunner's range (gunner also reaches, and is cheaper).
    # Use the sentinel only in the middle band where only it can hit the core.
    ec = self.enemy_core_pos
    if ec is not None:
        d2 = target.distance_squared(ec)
        use_gunner = d2 > _SENTINEL_ATTACK_RADIUS_SQ or d2 <= _GUNNER_ATTACK_RADIUS_SQ
    else:
        use_gunner = False
    if use_gunner:
        turret_cost = c.get_gunner_cost()[0]
        can_build_turret = c.can_build_gunner
        build_turret = c.build_gunner
    else:
        turret_cost = c.get_sentinel_cost()[0]
        can_build_turret = c.can_build_sentinel
        build_turret = c.build_sentinel

    # Road reservation down — upgrade when Ti lands (destroy is action-free,
    # so build_turret chains in).
    if our_road:
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
