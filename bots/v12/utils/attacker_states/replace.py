from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, GameConstants, Position, ResourceType, Team

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
_NO_TITANIUM_ATTACK_ABORT_TURNS = 6

_FRIENDLY_REPLACE_TYPES = frozenset({
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.ROAD,
    EntityType.CONVEYOR,
})
_HIJACK_TYPES = frozenset({EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER})
_DOWNSTREAM_RELAY_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
})
_FRIENDLY_TURRET_TYPES = frozenset({EntityType.GUNNER, EntityType.SENTINEL})

# Cardinal-reachable predecessors. Bridges are handled separately since they
# teleport and therefore aren't adjacent to their exit tile.
_PREDECESSOR_RELAYS = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.SPLITTER,
})
_CARDINAL = (Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST)


def _feeds_visible_friendly_turret(
    c: Controller,
    start_pos: Position,
    my_team: Team,
) -> bool:
    """Trace resource flow forward from start_pos to visible allied turrets."""
    visited: set[tuple[int, int]] = set()
    stack: list[Position] = [start_pos]
    W, H = c.get_map_width(), c.get_map_height()

    while stack:
        pos = stack.pop()
        key = (pos.x, pos.y)
        if key in visited:
            continue
        visited.add(key)

        if not (0 <= pos.x < W and 0 <= pos.y < H) or not c.is_in_vision(pos):
            continue

        bld_id = c.get_tile_building_id(pos)
        if bld_id is None:
            continue

        etype = c.get_entity_type(bld_id)
        if c.get_team(bld_id) == my_team and etype in _FRIENDLY_TURRET_TYPES:
            return True

        if etype not in _DOWNSTREAM_RELAY_TYPES:
            continue

        if etype == EntityType.BRIDGE:
            stack.append(c.get_bridge_target(bld_id))
            continue

        facing = c.get_direction(bld_id)
        if facing == Direction.CENTRE:
            continue

        if etype == EntityType.SPLITTER:
            stack.append(pos.add(facing))
            stack.append(pos.add(facing.rotate_left().rotate_left()))
            stack.append(pos.add(facing.rotate_right().rotate_right()))
        else:
            stack.append(pos.add(facing))

    return False


def _try_build_adjacent_launcher(c: Controller, me: Position, my_team: Team) -> bool:
    if c.get_action_cooldown() > 0:
        return False
    if c.get_global_resources()[0] < c.get_launcher_cost()[0]:
        return False
    if c.get_unit_count() >= GameConstants.MAX_TEAM_UNITS:
        return False

    W, H = c.get_map_width(), c.get_map_height()

    def has_adjacent_launcher(pos: Position) -> bool:
        for d in _STEP_OFF:
            adj = pos.add(d)
            if not (0 <= adj.x < W and 0 <= adj.y < H):
                continue
            bid = c.get_tile_building_id(adj)
            if (
                bid is not None
                and c.get_entity_type(bid) == EntityType.LAUNCHER
                and c.get_team(bid) == my_team
            ):
                return True
        return False

    for d in _STEP_OFF:
        pos = me.add(d)
        if not (0 <= pos.x < W and 0 <= pos.y < H):
            continue
        if has_adjacent_launcher(pos):
            continue
        if c.get_tile_builder_bot_id(pos) is not None:
            continue

        bid = c.get_tile_building_id(pos)
        if bid is None:
            if c.can_build_launcher(pos):
                c.build_launcher(pos)
                return True
            continue

        etype = c.get_entity_type(bid)
        if etype == EntityType.MARKER:
            if c.can_build_launcher(pos):
                c.build_launcher(pos)
                return True
            continue

        if etype == EntityType.ROAD and c.get_team(bid) == my_team and c.can_destroy(pos):
            c.destroy(pos)
            if c.can_build_launcher(pos):
                c.build_launcher(pos)
                return True
    return False


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
    key = (target.x, target.y)
    committed = self._replace_commit_key == key

    bld_id = c.get_tile_building_id(target)
    team = c.get_team(bld_id) if bld_id is not None else None
    etype = c.get_entity_type(bld_id) if bld_id is not None else None
    bb = c.get_tile_builder_bot_id(target) if target is not None else None

    if bb is not None and bb != c.get_id():
        # early return when a not-us bb is on the tile and reset state as normal
        return True
    if etype in _DOWNSTREAM_RELAY_TYPES and _feeds_visible_friendly_turret(
        c, target, my_team
    ):
        self.blacklist[key] = c.get_current_round()
        return True

    match (team, etype):
        case (_, EntityType.MARKER):
            replace_surface = etype
        case (t, EntityType.SENTINEL | EntityType.GUNNER) if t == my_team:
            return True
        case (t, _) if t not in (None, my_team):
            # Enemy on target: walk on (conveyor is walkable) and own-tile fire.
            if me == target:
                if self._attack_target_key != key:
                    self._attack_target_key = key
                    self._attack_turns = 0
                    self._attack_max_hp = c.get_max_hp(bld_id)
                    self._attack_no_titanium_turns = 0
                    self._attack_hp_after_fire = None
                hp_now = c.get_hp(bld_id)
                if (
                    self._attack_hp_after_fire is not None
                    and hp_now > self._attack_hp_after_fire
                ):
                    self.blacklist[key] = c.get_current_round()
                    return True
                if c.get_stored_resource(bld_id) == ResourceType.TITANIUM:
                    self._attack_no_titanium_turns = 0
                else:
                    self._attack_no_titanium_turns += 1
                    if self._attack_no_titanium_turns >= _NO_TITANIUM_ATTACK_ABORT_TURNS:
                        self.blacklist[key] = c.get_current_round()
                        return True
                if self._attack_turns >= 1 and hp_now > self._attack_max_hp - 2:
                    self.blacklist[key] = c.get_current_round()
                    return True
                if _try_build_adjacent_launcher(c, me, my_team):
                    return False
                if c.can_fire(me):
                    c.fire(me)
                    self._replace_commit_key = key
                    self._attack_turns += 1
                    after_fire_id = c.get_tile_building_id(target)
                    self._attack_hp_after_fire = (
                        c.get_hp(after_fire_id) if after_fire_id is not None else None
                    )
            elif c.can_move(me.direction_to(target)):
                c.move(me.direction_to(target))
            return False
        case (t, EntityType.ROAD | EntityType.CONVEYOR) if t == my_team:
            replace_surface = etype
        case (None, _):
            replace_surface = None
        case _:
            # Friendly stray (not road/conveyor/turret) — tear it down.
            if c.can_destroy(target):
                c.destroy(target)
            return False

    # Turrets are expensive — only commit if titanium is still flowing here.
    if not committed and not _titanium_reaches(c, target):
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
    if ti < turret_cost:
        return False

    if replace_surface in (EntityType.ROAD, EntityType.CONVEYOR):
        if not c.can_destroy(target):
            return False
        c.destroy(target)
        self._replace_commit_key = key

    if can_build_turret(target, facing):
        build_turret(target, facing)
        return True
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
    if et == EntityType.MARKER:
        return True
    if et in _DOWNSTREAM_RELAY_TYPES and _feeds_visible_friendly_turret(
        c, target, c.get_team()
    ):
        return False
    if c.get_team(bld_id) == c.get_team():
        return et in _FRIENDLY_REPLACE_TYPES
    return et in _HIJACK_TYPES


def replace(self: Attacker, c: Controller) -> None:
    if _execute_replacement(self, c):
        self.target_conveyor = None
        self._planner_goal = None
        self._reset_replace_tracking()
        self.state = AttackState.SCAN
