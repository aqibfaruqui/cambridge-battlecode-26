from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Position, ResourceType

from utils.attacker_states.state import AttackState

if TYPE_CHECKING:
    from builders.attacker import Attacker


_STEP_OFF = (
    Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST,
    Direction.NORTHEAST, Direction.SOUTHEAST, Direction.SOUTHWEST, Direction.NORTHWEST,
)

# Only the band _GUNNER < d² <= _SENTINEL needs the pricier sentinel.
_SENTINEL_ATTACK_RADIUS_SQ = 32
_GUNNER_ATTACK_RADIUS_SQ = 9

_FRIENDLY_REPLACE_TYPES = frozenset({EntityType.SENTINEL, EntityType.GUNNER, EntityType.ROAD})
_HIJACK_TYPES = frozenset({EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER})

# Cardinal-reachable predecessors. Bridges are handled separately since they
# teleport and therefore aren't adjacent to their exit tile.
_PREDECESSOR_RELAYS = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
})
_CARDINAL = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)


def _flows_into(
    c: Controller,
    pred_pos: Position,
    pred_id: int,
    etype: EntityType,
    target: Position,
) -> bool:
    facing = c.get_direction(pred_id)
    if facing == Direction.CENTRE:
        return False
    if etype == EntityType.SPLITTER:
        out_dirs = (
            facing,
            facing.rotate_left().rotate_left(),
            facing.rotate_right().rotate_right(),
        )
    else:
        out_dirs = (facing,)
    for od in out_dirs:
        out = pred_pos.add(od)
        if out.x == target.x and out.y == target.y:
            return True
    return False


def _titanium_reaches(c: Controller, target: Position) -> bool:
    """Backward-trace the relay graph from `target`; True iff some upstream
    relay in vision currently stores TITANIUM. Adjacency only finds
    conveyors/splitters; bridges are pre-indexed by their exit tile."""
    W, H = c.get_map_width(), c.get_map_height()

    bridges_by_exit: dict[tuple[int, int], list[int]] = {}
    for bid in c.get_nearby_buildings():
        if c.get_entity_type(bid) != EntityType.BRIDGE:
            continue
        ex = c.get_bridge_target(bid)
        bridges_by_exit.setdefault((ex.x, ex.y), []).append(bid)

    visited: set[tuple[int, int]] = set()
    stack: list[Position] = [target]
    while stack:
        pos = stack.pop()
        key = (pos.x, pos.y)
        if key in visited:
            continue
        visited.add(key)

        for d in _CARDINAL:
            pred = pos.add(d)
            if not (0 <= pred.x < W and 0 <= pred.y < H) or not c.is_in_vision(pred):
                continue
            pred_id = c.get_tile_building_id(pred)
            if pred_id is None:
                continue
            etype = c.get_entity_type(pred_id)
            if etype not in _PREDECESSOR_RELAYS:
                continue
            if not _flows_into(c, pred, pred_id, etype, pos):
                continue
            if c.get_stored_resource(pred_id) == ResourceType.TITANIUM:
                return True
            stack.append(pred)

        for bid in bridges_by_exit.get(key, ()):
            if c.get_stored_resource(bid) == ResourceType.TITANIUM:
                return True
            stack.append(c.get_position(bid))

    return False


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
            return True
        case (t, _) if t not in (None, my_team):
            # Enemy on target: walk on (conveyor is walkable) and own-tile fire.
            if me == target:
                key = (target.x, target.y)
                if self._attack_target_key != key:
                    self._attack_target_key = key
                    self._attack_turns = 0
                    self._attack_max_hp = c.get_max_hp(bld_id)
                if self._attack_turns >= 1 and c.get_hp(bld_id) > self._attack_max_hp - 2:
                    self.blacklist[key] = c.get_current_round()
                    return True
                if c.can_fire(me):
                    c.fire(me)
                    self._attack_turns += 1
            elif c.can_move(me.direction_to(target)):
                c.move(me.direction_to(target))
            return False
        case (t, EntityType.ROAD) if t == my_team:
            our_road = True
        case (None, _):
            our_road = False
        case _:
            # Friendly stray (not road, not turret) — tear it down.
            if c.can_destroy(target):
                c.destroy(target)
            return False

    # Turrets are expensive — only commit if titanium is still flowing here.
    if not _titanium_reaches(c, target):
        self.blacklist[(target.x, target.y)] = c.get_current_round()
        return True

    # Step off (move cd is separate from action cd, so the build below chains).
    if me == target:
        step = next((d for d in _STEP_OFF if c.can_move(d)), None)
        if step is None:
            self.blacklist[(target.x, target.y)] = c.get_current_round()
            return True
        c.move(step)
        me = c.get_position()

    ec = self.enemy_core_pos
    facing = me.direction_to(target)
    if ec is not None and (d := target.direction_to(ec)) != Direction.CENTRE:
        facing = d

    use_gunner = ec is not None and (
        (d2 := target.distance_squared(ec)) > _SENTINEL_ATTACK_RADIUS_SQ
        or d2 <= _GUNNER_ATTACK_RADIUS_SQ
    )
    turret_cost, can_build_turret, build_turret = (
        (c.get_gunner_cost()[0], c.can_build_gunner, c.build_gunner)
        if use_gunner else
        (c.get_sentinel_cost()[0], c.can_build_sentinel, c.build_sentinel)
    )

    ti = c.get_global_resources()[0]
    if our_road:
        # Upgrade the road to a turret once Ti lands.
        if ti >= turret_cost and c.can_destroy(target):
            c.destroy(target)
            if can_build_turret(target, facing):
                build_turret(target, facing)
                return True
        return False

    # Empty target: turret if affordable, else a 1-Ti road to reserve.
    if ti >= turret_cost and can_build_turret(target, facing):
        build_turret(target, facing)
        return True
    if c.can_build_road(target):
        c.build_road(target)
    return False


def target_still_valid(self: Attacker, c: Controller) -> bool:
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
        return et in _FRIENDLY_REPLACE_TYPES
    return et in _HIJACK_TYPES


def replace(self: Attacker, c: Controller) -> None:
    if _execute_replacement(self, c):
        self.target_conveyor = None
        self._planner_goal = None
        self.state = AttackState.SCAN
