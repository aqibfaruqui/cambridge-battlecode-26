from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType

from utils.attacker_states.state import AttackState

if TYPE_CHECKING:
    from builders.attacker_revamped import AttackerRevamped


_STEP_OFF = (
    Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
    Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST,
)


def _execute_replacement(self: AttackerRevamped, c: Controller) -> bool:
    """Attack, step off, drop a sentinel on the same tile we attacked."""
    target = self.target_conveyor
    assert target is not None
    me = self.current_pos
    my_team = c.get_team()

    bld_id = c.get_tile_building_id(target)
    team = c.get_team(bld_id) if bld_id is not None else None
    etype = c.get_entity_type(bld_id) if bld_id is not None else None

    # Sentinel already placed — done.
    if team == my_team and etype == EntityType.SENTINEL:
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
    sent_cost = c.get_sentinel_cost()[0]

    # Road reservation down — upgrade when Ti lands (destroy is action-free,
    # so build_sentinel chains in).
    if our_road:
        if ti >= sent_cost and c.can_destroy(target):
            c.destroy(target)
            if c.can_build_sentinel(target, facing):
                c.build_sentinel(target, facing)
                self.sentinels_placed += 1
                return True
        return False

    # Empty target: sentinel if affordable, else a 1-Ti road to reserve.
    if ti >= sent_cost and c.can_build_sentinel(target, facing):
        c.build_sentinel(target, facing)
        self.sentinels_placed += 1
        return True
    if c.can_build_road(target):
        c.build_road(target)
    return False


def _target_still_valid(self: AttackerRevamped, c: Controller) -> bool:
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
        return et in (EntityType.SENTINEL, EntityType.ROAD)
    return et in (EntityType.CONVEYOR, EntityType.BRIDGE)


def _replace(self: AttackerRevamped, c: Controller) -> None:
    if _execute_replacement(self, c):
        self.target_conveyor = None
        self._planner_goal = None
        self.state = AttackState.SCAN
