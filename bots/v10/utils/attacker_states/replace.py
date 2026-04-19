from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position

from utils.raw_map_representation import WALL

if TYPE_CHECKING:
    from builders.attacker_revamped import AttackerRevamped


_CARDINAL_OFFSETS = ((0, 1), (0, -1), (1, 0), (-1, 0))


def _cardinal_candidates(
    env, target: Position, W: int, H: int, primary: Position
) -> list[Position]:
    """In-bounds, non-wall cardinals around `target`, `primary` first"""
    seen: set[tuple[int, int]] = set()
    order = [primary] + [
        Position(target.x + dx, target.y + dy) for dx, dy in _CARDINAL_OFFSETS
    ]
    out: list[Position] = []
    for p in order:
        if not (0 <= p.x < W and 0 <= p.y < H):
            continue
        if env.tile(p.x, p.y) & (1 << WALL):
            continue
        key = (p.x, p.y)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _execute_replacement(self: AttackerRevamped, c: Controller) -> bool:
    """Clear target → splitter → sentinel (with cheap reservation)."""
    target = self.target_conveyor
    direction = self.target_direction
    sentinel_tile = self.sentinel_tile
    assert target is not None and direction is not None and sentinel_tile is not None

    my_team = c.get_team()
    me = self.current_pos

    # Stages 1 & 2: get our splitter onto the target tile.
    t_bld_id = c.get_tile_building_id(target)
    t_is_our_splitter = (
        t_bld_id is not None
        and c.get_team(t_bld_id) == my_team
        and c.get_entity_type(t_bld_id) == EntityType.SPLITTER
    )
    if not t_is_our_splitter:
        if t_bld_id is not None:
            if c.get_team(t_bld_id) != my_team:
                # Enemy piece: walk onto it and fire.
                if me != target:
                    step = me.direction_to(target)
                    if c.can_move(step):
                        c.move(step)
                    return False
                if c.can_fire(target):
                    c.fire(target)
                return False
            # Friendly non-splitter: free tear-down from action radius.
            if c.can_destroy(target):
                c.destroy(target)
            return False
        # Empty target — stand on it and drop the splitter under ourselves.
        if me != target:
            step = me.direction_to(target)
            if c.can_move(step):
                c.move(step)
            return False
        if c.can_build_splitter(target, direction):
            c.build_splitter(target, direction)
        return False

    # Stage 3: splitter is up. Commit to a sentinel on some cardinal.
    env = self._env_map
    assert env is not None
    W, H = c.get_map_width(), c.get_map_height()
    cardinals = _cardinal_candidates(env, target, W, H, sentinel_tile)

    our_sentinel: Position | None = None
    reservation: Position | None = None
    empty: Position | None = None
    enemy: Position | None = None
    for p in cardinals:
        bld_id = c.get_tile_building_id(p)
        if bld_id is None:
            if empty is None:
                empty = p
            continue
        team = c.get_team(bld_id)
        et = c.get_entity_type(bld_id)
        if team == my_team and et == EntityType.SENTINEL:
            our_sentinel = p
            break
        if team == my_team and et == EntityType.CONVEYOR:
            if reservation is None:
                reservation = p
            continue
        if team != my_team and enemy is None:
            enemy = p

    if our_sentinel is not None:
        self.sentinels_placed += 1
        return True

    if reservation is not None:
        # Upgrade single-tick once we can afford it: destroy is free of
        # action cooldown, so we can follow it with build_sentinel.
        sent_cost = c.get_sentinel_cost()[0]
        ti = c.get_global_resources()[0]
        if ti < sent_cost or not c.can_destroy(reservation):
            return False
        c.destroy(reservation)
        facing = reservation.direction_to(self.enemy_core_pos or target)
        if reservation.add(facing) == target:
            facing = facing.rotate_right()
        if c.can_build_sentinel(reservation, facing):
            c.build_sentinel(reservation, facing)
            self.sentinels_placed += 1
            return True
        return False

    if empty is not None:
        # Sentinel is non-walkable — step off the tile before we can build.
        if me == empty:
            step = me.direction_to(target)
            if c.can_move(step):
                c.move(step)
            return False
        # Always drop a cheap conveyor reservation immediately, even if
        # we could afford a sentinel outright. Keeps the tile locked in
        # a single tick regardless of Ti; the reservation branch above
        # upgrades it to a sentinel the moment funds are there.
        if c.can_build_conveyor(empty, direction):
            c.build_conveyor(empty, direction)
        return False

    if enemy is not None:
        # No empty cardinal — walk onto this one and fire so next tick
        # falls into the empty branch and reserves it with our conveyor.
        if me != enemy:
            step = me.direction_to(enemy)
            if c.can_move(step):
                c.move(step)
            return False
        if c.can_fire(enemy):
            c.fire(enemy)
        return False

    # All four cardinals are walls — no sentinel site exists, bail.
    self.blacklist.add((target.x, target.y))
    return True


def _target_still_valid(self: AttackerRevamped, c: Controller) -> bool:
    """True if the locked-in target conveyor is still worth pursuing"""
    target = self.target_conveyor
    if target is None:
        return False
    if not c.is_in_vision(target):
        return True
    bld_id = c.get_tile_building_id(target)
    if bld_id is None:
        return True
    et = c.get_entity_type(bld_id)
    team = c.get_team(bld_id)
    if team == c.get_team() and et == EntityType.SPLITTER:
        return True
    if team != c.get_team() and et == EntityType.CONVEYOR:
        return True
    return False


def _replace(self: AttackerRevamped, c: Controller) -> None:
    done = _execute_replacement(self, c)
    if done:
        self.target_conveyor = None
        self.target_direction = None
        self.sentinel_tile = None
        self._planner_goal = None
        self.state = type(self.state).SCAN
