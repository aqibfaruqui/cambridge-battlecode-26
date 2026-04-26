
from __future__ import annotations
import sys
from typing import TYPE_CHECKING

from cambc import Direction, EntityType, Environment, Position, Controller, ResourceType

from utils.pathfinding.d_star import DStarLite, _RETURN_BLOCK_MASK
from utils.pathfinding.movement import (
    DIRECTIONS_4,
    get_direction_4,
    is_diagonal,
    split_diagonal,
    reached_core,
)


if TYPE_CHECKING:
    from builders.harvester import Harvester


_MAX_BRIDGE_FAILS = 3
_FOUNDRY_JOIN_DEBUG = True
_BRIDGE_JUMP_DEBUG = True

_ENEMY_WALKABLE_TYPES = (
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.ROAD,
)
_CHAIN_MEMORY_TTL = 80
_CHAIN_TRACE_LIMIT = 18
_TRANSPORT_TYPES = {
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
}


def _debug_foundry_join(c: Controller, reason: str, pos: Position | None = None) -> None:
    if not _FOUNDRY_JOIN_DEBUG:
        return
    suffix = "" if pos is None else f" pos=({pos.x},{pos.y})"
    print(
        f"[foundry_join] id={c.get_id()} r={c.get_current_round()} {reason}{suffix}",
        file=sys.stderr,
    )


def _debug_bridge(c: Controller, reason: str, extra: str = "") -> None:
    if not _BRIDGE_JUMP_DEBUG:
        return
    print(
        f"[bridge_jump] id={c.get_id()} r={c.get_current_round()} {reason}{(' ' + extra) if extra else ''}",
        file=sys.stderr,
    )


def _reset_return_state(self: Harvester):
    self.bridge_jump_target = None
    self.bridge_target_planner = None
    self.return_next_dir = None
    self.return_planner = None
    self.post_bridge_conveyor = False
    self.return_bridge_fail_counts = {}


def _clear_bridge_walk_state(self: Harvester, *, reset_return_planner: bool = False) -> None:
    self.bridge_jump_target = None
    self.bridge_target_planner = None
    if reset_return_planner:
        self.return_planner = None


def _start_bridge_walk(self: Harvester, target: Position) -> None:
    self.bridge_jump_target = target
    self.bridge_target_planner = None


def _bridge_target_matches(c: Controller, bridge_id: int, target: Position) -> bool:
    try:
        return c.get_bridge_target(bridge_id) == target
    except Exception:
        return True


def _bridge_fail(self: Harvester, c: Controller, key, reason: str, extra: str = "") -> None:
    fails = self.return_bridge_fail_counts.get(key, 0) + 1
    self.return_bridge_fail_counts[key] = fails
    if fails >= _MAX_BRIDGE_FAILS:
        _debug_bridge(c, reason, f"{extra} key={key} fails={fails}")
        _clear_bridge_walk_state(self, reset_return_planner=True)
        self.return_bridge_fail_counts.pop(key, None)


def _post_bridge_fail(self: Harvester, c: Controller, key, reason: str, extra: str = "") -> None:
    fails = self.return_bridge_fail_counts.get(key, 0) + 1
    self.return_bridge_fail_counts[key] = fails
    if fails >= _MAX_BRIDGE_FAILS:
        _debug_bridge(c, reason, f"{extra} key={key} fails={fails}")
        self.post_bridge_conveyor = False
        self.return_planner = None
        self.return_bridge_fail_counts.pop(key, None)


def _enemy_walkable_at(c: Controller, pos: Position) -> bool:
    if not _on_map(c, pos) or not c.is_in_vision(pos):
        return False
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return False
    if c.get_team(bid) == c.get_team():
        return False
    return c.get_entity_type(bid) in _ENEMY_WALKABLE_TYPES


def _attack_enemy_under_bot(self: Harvester, c: Controller) -> bool:
    if not _enemy_walkable_at(c, self.current_pos):
        return False
    if c.can_fire(self.current_pos):
        c.fire(self.current_pos)
        if c.get_tile_building_id(self.current_pos) is None:
            self.post_bridge_conveyor = True
    return True


def _return_dynamic_blockers(c: Controller) -> list[tuple[int, int]]:
    team = c.get_team()
    blockers: list[tuple[int, int]] = []
    for pos in c.get_nearby_tiles():
        build_id = c.get_tile_building_id(pos)
        if build_id is None:
            continue
        entity_type = c.get_entity_type(build_id)
        if entity_type == EntityType.MARKER:
            continue
        if entity_type in (EntityType.BUILDER_BOT, EntityType.HARVESTER) or c.get_team(build_id) != team:
            blockers.append((pos.x, pos.y))
    return blockers


def _ensure_return_planner(self: Harvester, c: Controller):
    if self.return_planner is None and self.environment_map is not None:
        self.return_planner = DStarLite(
            self.environment_map,
            self.core_pos.x,
            self.core_pos.y,
            block_mask=_RETURN_BLOCK_MASK,
            unknown_cost=3.0,
            use_bridges=True,
        )
    p = self.return_planner
    if p is not None:
        p.set_dynamic_blockers(_return_dynamic_blockers(c))
        p.notify_map_changes()
    return p


def _planner_step_at(self: Harvester, c: Controller, pos: Position) -> Direction | None:
    p = _ensure_return_planner(self, c)
    if p is None:
        return None
    p.set_position(pos.x, pos.y)
    step = p.step()
    return None if step == Direction.CENTRE else step


def _clear_return_tile(_: Harvester, c: Controller, pos: Position) -> bool:
    build_id = c.get_tile_building_id(pos)
    if build_id is None:
        return True
    entity_type = c.get_entity_type(build_id)
    if entity_type in (EntityType.MARKER, EntityType.CORE):
        return True
    if entity_type == EntityType.ROAD:
        if c.can_destroy(pos):
            c.destroy(pos)
            return True
        return False
    if c.get_team(build_id) != c.get_team():
        return False
    return entity_type in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE)


def _allied_conveyor_at(c: Controller, pos: Position) -> int | None:
    if not _on_map(c, pos) or not c.is_in_vision(pos):
        return None
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return None
    if c.get_team(bid) != c.get_team():
        return None
    if c.get_entity_type(bid) != EntityType.CONVEYOR:
        return None
    return bid


def _allied_transport_at(c: Controller, pos: Position) -> int | None:
    if not _on_map(c, pos) or not c.is_in_vision(pos):
        return None
    bid = c.get_tile_building_id(pos)
    if bid is None or c.get_team(bid) != c.get_team():
        return None
    if c.get_entity_type(bid) not in _TRANSPORT_TYPES:
        return None
    return bid


def _transport_output(c: Controller, pos: Position, bid: int) -> Position | None:
    etype = c.get_entity_type(bid)
    if etype == EntityType.BRIDGE:
        try:
            return c.get_bridge_target(bid)
        except Exception:
            return None
    try:
        direction = c.get_direction(bid)
    except Exception:
        return None
    if direction is None or direction == Direction.CENTRE:
        return None
    if etype == EntityType.SPLITTER and direction not in DIRECTIONS_4:
        return None
    return pos.add(direction)


def _transport_output_from_memory(entry: dict) -> Position | None:
    out = entry.get("out")
    if out is None:
        return None
    return Position(out[0], out[1])


def _chain_memory_entry(self: Harvester, pos: Position) -> dict | None:
    return self.chain_memory.get((pos.x, pos.y))


def _update_chain_memory(self: Harvester, c: Controller) -> None:
    """Remember nearby allied transport so axionite can join real titanium chains."""
    now = c.get_current_round()
    stale_before = now - _CHAIN_MEMORY_TTL
    for key, entry in list(self.chain_memory.items()):
        if entry.get("round", 0) < stale_before:
            self.chain_memory.pop(key, None)

    for pos in c.get_nearby_tiles():
        bid = _allied_transport_at(c, pos)
        if bid is None:
            continue

        stored = c.get_stored_resource(bid)
        entry = self.chain_memory.get((pos.x, pos.y), {})
        if stored == ResourceType.TITANIUM:
            entry["last_titanium_round"] = now
        entry.update(
            {
                "round": now,
                "type": c.get_entity_type(bid),
                "out": (
                    None
                    if (out := _transport_output(c, pos, bid)) is None
                    else (out.x, out.y)
                ),
                "resource": stored,
                "resource_id": c.get_stored_resource_id(bid),
                "dist_core": max(abs(pos.x - self.core_pos.x), abs(pos.y - self.core_pos.y)),
            }
        )
        self.chain_memory[(pos.x, pos.y)] = entry


def _on_map(c: Controller, pos: Position) -> bool:
    return 0 <= pos.x < c.get_map_width() and 0 <= pos.y < c.get_map_height()


def _near_allied_harvester(c: Controller, pos: Position) -> bool:
    for direction in DIRECTIONS_4:
        neighbor = pos.add(direction)
        if not _on_map(c, neighbor) or not c.is_in_vision(neighbor):
            continue
        bid = c.get_tile_building_id(neighbor)
        if (
            bid is not None
            and c.get_team(bid) == c.get_team()
            and c.get_entity_type(bid) == EntityType.HARVESTER
        ):
            return True
    return False


def _ensure_current_feeds_join(self: Harvester, c: Controller, join_pos: Position) -> bool:
    feed_dir = self.current_pos.direction_to(join_pos)
    if feed_dir not in DIRECTIONS_4:
        return False

    bid = c.get_tile_building_id(self.current_pos)
    if bid is not None:
        stored = c.get_stored_resource(bid) if c.get_entity_type(bid) in _TRANSPORT_TYPES else None
        if stored is not None and stored != ResourceType.RAW_AXIONITE:
            return False
        return (
            c.get_team(bid) == c.get_team()
            and c.get_entity_type(bid) == EntityType.CONVEYOR
            and c.get_direction(bid) == feed_dir
        )
    return False


def _visible_or_remembered_transport(
    self: Harvester, c: Controller, pos: Position
) -> tuple[EntityType | None, Position | None, ResourceType | None, int]:
    bid = _allied_transport_at(c, pos)
    if bid is not None:
        return (
            c.get_entity_type(bid),
            _transport_output(c, pos, bid),
            c.get_stored_resource(bid),
            c.get_current_round(),
        )

    entry = _chain_memory_entry(self, pos)
    if entry is None:
        return None, None, None, -1
    return (
        entry.get("type"),
        _transport_output_from_memory(entry),
        entry.get("resource"),
        entry.get("last_titanium_round", -1),
    )


def _chain_reaches_core(self: Harvester, c: Controller, start: Position) -> bool:
    seen: set[tuple[int, int]] = set()
    pos = start
    for _ in range(_CHAIN_TRACE_LIMIT):
        if not _on_map(c, pos):
            return False
        if reached_core(pos, self.core_pos):
            return True
        key = (pos.x, pos.y)
        if key in seen:
            return False
        seen.add(key)

        if c.is_in_vision(pos):
            bid = c.get_tile_building_id(pos)
            if bid is not None and c.get_team(bid) == c.get_team() and c.get_entity_type(bid) == EntityType.CORE:
                return True

        _, out, _, _ = _visible_or_remembered_transport(self, c, pos)
        if out is None:
            return False
        pos = out
    return False


def _candidate_join_score(self: Harvester, c: Controller, join_pos: Position) -> int | None:
    if self.harvester_pos is not None and join_pos.distance_squared(self.harvester_pos) <= 2:
        return None
    if _near_allied_harvester(c, join_pos):
        return None

    join_id = _allied_conveyor_at(c, join_pos)
    if join_id is None:
        return None
    if c.get_stored_resource(join_id) == ResourceType.RAW_AXIONITE:
        return None

    feed_dir = self.current_pos.direction_to(join_pos)
    if feed_dir not in DIRECTIONS_4:
        return None

    original_dir = c.get_direction(join_id)
    if original_dir not in DIRECTIONS_4:
        return None

    out_pos = join_pos.add(original_dir)
    if not _chain_reaches_core(self, c, out_pos):
        return None

    score = 100
    if c.get_stored_resource(join_id) == ResourceType.TITANIUM:
        score += 80

    entry = _chain_memory_entry(self, join_pos)
    if entry is not None:
        if entry.get("resource") == ResourceType.TITANIUM:
            score += 35
        last_ti = entry.get("last_titanium_round", -1)
        if last_ti >= 0:
            age = c.get_current_round() - last_ti
            if age <= _CHAIN_MEMORY_TTL:
                score += max(0, 40 - age)

    if out_pos.distance_squared(self.core_pos) < join_pos.distance_squared(self.core_pos):
        score += 20
    # Prefer the tile the return planner already wanted when return_next_dir is
    # carrying a delayed move from the previous tick.
    planned = self.current_pos.add(self.return_next_dir) if self.return_next_dir else None
    if planned is not None and planned == join_pos:
        score += 10
    score -= max(abs(join_pos.x - self.core_pos.x), abs(join_pos.y - self.core_pos.y))
    return score


def _finish_foundry_join(self: Harvester, c: Controller, join_pos: Position) -> None:
    _debug_foundry_join(c, "built_foundry", join_pos)
    self.foundry_curr_placed = True
    self.foundry_prev_placed = True
    self.foundry_placed_round = c.get_current_round()
    self.returning_from_axionite = False
    self.target_pos = None
    self.seek_target_is_ore = False
    self.harvester_pos = None
    self.chain_memory.pop((join_pos.x, join_pos.y), None)
    _reset_return_state(self)
    self.state = type(self.state).SEEK


def _try_join_axionite_to_titanium_chain(
    self: Harvester, c: Controller, join_pos: Position
) -> bool:
    if not self.returning_from_axionite:
        return False
    if self.foundry_prev_placed:
        _debug_foundry_join(c, "skip_foundry_already_marked", join_pos)
        return False

    # The foundry must be the exact intersection tile: the next tile on the
    # axionite return path, which is also a verified titanium conveyor chain.
    if _candidate_join_score(self, c, join_pos) is None:
        return False

    join_id = _allied_conveyor_at(c, join_pos)
    if join_id is None:
        return False

    feed_dir = self.current_pos.direction_to(join_pos)
    current_id = c.get_tile_building_id(self.current_pos)
    if current_id is not None and c.get_entity_type(current_id) in (EntityType.MARKER, EntityType.ROAD):
        if c.can_destroy(self.current_pos):
            c.destroy(self.current_pos)
            _debug_foundry_join(c, "cleared_feed_tile_wait", join_pos)
            return True
    if current_id is None and c.get_tile_env(self.current_pos) == Environment.EMPTY:
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if self.ti >= conveyor_cost_ti and c.can_build_conveyor(self.current_pos, feed_dir):
            c.build_conveyor(self.current_pos, feed_dir)
            _debug_foundry_join(c, "built_feed_conveyor_wait", join_pos)
            return True
        if self.ti >= conveyor_cost_ti:
            _debug_foundry_join(c, "wait_feed_conveyor_action", join_pos)
            return True

    foundry_cost_ti, _ = c.get_foundry_cost()
    if self.ti < foundry_cost_ti:
        _debug_foundry_join(c, f"wait_ti_{self.ti}_need_{foundry_cost_ti}", join_pos)
        return True

    original_dir = c.get_direction(join_id)
    if not _ensure_current_feeds_join(self, c, join_pos):
        _debug_foundry_join(c, "skip_cannot_feed_join", join_pos)
        return False

    if not c.can_destroy(join_pos):
        _debug_foundry_join(c, "skip_cannot_destroy_join", join_pos)
        return False

    c.destroy(join_pos)
    if c.can_build_foundry(join_pos):
        c.build_foundry(join_pos)
        _finish_foundry_join(self, c, join_pos)
        return True

    _debug_foundry_join(c, "failed_can_build_foundry_after_destroy", join_pos)
    if c.can_build_conveyor(join_pos, original_dir):
        c.build_conveyor(join_pos, original_dir)
    self.returning_from_axionite = False
    return False


def _next_dir_after_move(self: Harvester, c: Controller, move_dir: Direction) -> Direction | None:
    """Conveyor direction to place on the tile we're about to step onto."""
    move_pos = self.current_pos.add(move_dir)
    follow_dir = _planner_step_at(self, c, move_pos) or move_pos.direction_to(self.core_pos)
    if follow_dir is None or follow_dir == Direction.CENTRE:
        return None
    if follow_dir in DIRECTIONS_4:
        return follow_dir
    return get_direction_4(move_pos, move_pos.add(follow_dir))


def _handle_post_bridge_conveyor(self: Harvester, c: Controller) -> bool:
    """Place conveyor on current tile after crossing a bridge. Returns True while consuming the turn."""
    if not self.post_bridge_conveyor:
        return False

    if reached_core(self.current_pos, self.core_pos):
        self.post_bridge_conveyor = False
        return True

    conveyor_dir = _planner_step_at(self, c, self.current_pos)
    key = ("post_bridge", self.current_pos.x, self.current_pos.y)
    if conveyor_dir is None:
        _post_bridge_fail(self, c, key, "post_conveyor_no_dstar_dir")
        return True
    if conveyor_dir == Direction.CENTRE or conveyor_dir not in DIRECTIONS_4:
        _post_bridge_fail(self, c, key, "post_conveyor_bad_dstar_dir", f"dir={conveyor_dir}")
        return True

    bid = c.get_tile_building_id(self.current_pos)
    if bid is not None:
        etype = c.get_entity_type(bid)
        allied = c.get_team(bid) == c.get_team()
        if allied and etype == EntityType.CONVEYOR:
            if c.get_direction(bid) == conveyor_dir:
                self.return_next_dir = conveyor_dir
                self.post_bridge_conveyor = False
                self.return_bridge_fail_counts.pop(key, None)
            elif c.can_destroy(self.current_pos):
                c.destroy(self.current_pos)
            return True
        if etype == EntityType.ROAD:
            if c.get_tile_env(self.current_pos) == Environment.EMPTY and c.can_destroy(self.current_pos):
                c.destroy(self.current_pos)
            else:
                self.return_next_dir = conveyor_dir
                self.post_bridge_conveyor = False
            return True

    if _clear_return_tile(self, c, self.current_pos):
        tile_empty = c.get_tile_env(self.current_pos) == Environment.EMPTY
        ti, _ = c.get_global_resources()
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if tile_empty and ti >= conveyor_cost_ti and c.can_build_conveyor(self.current_pos, conveyor_dir):
            c.build_conveyor(self.current_pos, conveyor_dir)

        bid = c.get_tile_building_id(self.current_pos)
        connected = bid is not None and c.get_team(bid) == c.get_team() and c.get_entity_type(bid) in (
            EntityType.CONVEYOR,
            EntityType.SPLITTER,
            EntityType.BRIDGE,
        )
        if connected:
            self.return_next_dir = conveyor_dir
            self.post_bridge_conveyor = False
            self.return_bridge_fail_counts.pop(key, None)
        elif not tile_empty or ti >= conveyor_cost_ti:
            _post_bridge_fail(self, c, key, "post_conveyor_give_up", f"dir={conveyor_dir}")

    return True


def _handle_bridge_jump(self: Harvester, c: Controller, target_pos: Position) -> bool:
    """Build a bridge to target_pos if not built yet, then walk across it."""
    bridge_pos = self.current_pos

    if self.bridge_jump_target is not None:
        _debug_bridge(c, "walk_resume", f"cur=({self.current_pos.x},{self.current_pos.y}) target=({self.bridge_jump_target.x},{self.bridge_jump_target.y})")
        return _walk_toward_bridge_target(self, c)

    bid = c.get_tile_building_id(bridge_pos)
    entity_type = c.get_entity_type(bid) if bid is not None else None
    allied = bid is not None and c.get_team(bid) == c.get_team()

    if allied and entity_type == EntityType.BRIDGE and _bridge_target_matches(c, bid, target_pos):
        _debug_bridge(c, "bridge_exists_start_walk", f"cur=({bridge_pos.x},{bridge_pos.y}) target=({target_pos.x},{target_pos.y})")
        _start_bridge_walk(self, target_pos)
        return _walk_toward_bridge_target(self, c)

    if allied and entity_type in (EntityType.ROAD, EntityType.CONVEYOR, EntityType.BRIDGE):
        ti, _ = c.get_global_resources()
        bridge_cost_ti, _ = c.get_bridge_cost()
        if ti < bridge_cost_ti or not c.can_destroy(bridge_pos):
            _debug_bridge(c, "wait_ti_for_bridge_destroy", f"ti={ti} need={bridge_cost_ti}")
            return True
        c.destroy(bridge_pos)

    if c.can_build_bridge(bridge_pos, target_pos):
        c.build_bridge(bridge_pos, target_pos)
        _debug_bridge(c, "built_bridge", f"from=({bridge_pos.x},{bridge_pos.y}) to=({target_pos.x},{target_pos.y})")
        _start_bridge_walk(self, target_pos)
        return True

    ti, _ = c.get_global_resources()
    bridge_cost_ti, _ = c.get_bridge_cost()
    _debug_bridge(c, "cannot_build_bridge", f"from=({bridge_pos.x},{bridge_pos.y}) to=({target_pos.x},{target_pos.y}) ti={ti} need={bridge_cost_ti} existing={entity_type}")
    if ti >= bridge_cost_ti:
        key = (bridge_pos.x, bridge_pos.y, target_pos.x, target_pos.y)
        _bridge_fail(self, c, key, "bridge_fail_reset_planner")
    return True


def _ensure_bridge_target_planner(self: Harvester, c: Controller, target: Position) -> DStarLite | None:
    if self.bridge_target_planner is None and self.environment_map is not None:
        self.bridge_target_planner = DStarLite(
            self.environment_map,
            target.x,
            target.y,
            block_mask=_RETURN_BLOCK_MASK,
        )
    p = self.bridge_target_planner
    if p is not None:
        p.set_position(self.current_pos.x, self.current_pos.y)
        p.set_dynamic_blockers(_return_dynamic_blockers(c))
        p.notify_map_changes()
    return p


def _complete_return_from_bridge(self: Harvester, c: Controller) -> None:
    if self._can_trigger_foundry(c):
        self.state = type(self.state).PLACING_FOUNDRY
    elif self.harvesters_placed >= 1:
        self.patrol_tip = self.harvester_pos
        self.patrol_turns = 0
        self.patrol_target = None
        self.patrol_going_out = True
        self.state = type(self.state).PATROL
    else:
        self.state = type(self.state).SEEK
    self.target_pos = None
    self.seek_target_is_ore = False
    self.harvester_pos = None
    self.returning_from_axionite = False
    _reset_return_state(self)


_BRIDGE_WALKABLE_TYPES = (
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.ROAD,
)


def _can_execute_bridge_walk_step(c: Controller, move_dir: Direction) -> bool:
    """Return True if the bridge-walk can proceed in move_dir this round."""
    move_pos = c.get_position().add(move_dir)
    if c.can_move(move_dir):
        return True
    if not _on_map(c, move_pos):
        if _BRIDGE_JUMP_DEBUG:
            print(f"[bridge_walk_step] r={c.get_current_round()} dir={move_dir} BLOCKED:off_map pos=({move_pos.x},{move_pos.y})", file=sys.stderr)
        return False
    tile_env = c.get_tile_env(move_pos)
    build_id = c.get_tile_building_id(move_pos)
    if build_id is not None:
        etype = c.get_entity_type(build_id)
        # Markers are walkable and we can build over them.
        if etype == EntityType.MARKER:
            return True
        if etype in _BRIDGE_WALKABLE_TYPES:
            if _BRIDGE_JUMP_DEBUG:
                print(f"[bridge_walk_step] r={c.get_current_round()} dir={move_dir} BLOCKED:walkable_building_can_move_false:{etype} pos=({move_pos.x},{move_pos.y})", file=sys.stderr)
            return False
        if _BRIDGE_JUMP_DEBUG:
            print(f"[bridge_walk_step] r={c.get_current_round()} dir={move_dir} BLOCKED:building={etype} pos=({move_pos.x},{move_pos.y})", file=sys.stderr)
        return False
    # No building: empty tiles and tiles where we can build a road are reachable.
    # Empty land tiles are directly walkable; water tiles need a road first.
    if tile_env == Environment.EMPTY:
        return True
    if c.can_build_road(move_pos):
        return True
    if _BRIDGE_JUMP_DEBUG:
        print(f"[bridge_walk_step] r={c.get_current_round()} dir={move_dir} BLOCKED:env={tile_env} pos=({move_pos.x},{move_pos.y})", file=sys.stderr)
    return False

def _walk_toward_bridge_target(self: Harvester, c: Controller) -> bool:
    target = self.bridge_jump_target
    if target is None:
        return False

    _debug_bridge(c, "walk_tick", f"cur=({self.current_pos.x},{self.current_pos.y}) target=({target.x},{target.y}) core=({self.core_pos.x},{self.core_pos.y})")

    if reached_core(self.current_pos, self.core_pos):
        _debug_bridge(c, "walk_current_is_core_complete")
        _complete_return_from_bridge(self, c)
        return True

    if self.current_pos == target:
        if reached_core(target, self.core_pos):
            _debug_bridge(c, "walk_reached_core_target_complete", f"pos=({target.x},{target.y})")
            _complete_return_from_bridge(self, c)
            return True
        _debug_bridge(c, "walk_reached_target_set_post_conveyor", f"pos=({target.x},{target.y})")
        _clear_bridge_walk_state(self)
        self.post_bridge_conveyor = True
        return True

    p = _ensure_bridge_target_planner(self, c, target)
    move_dir = p.step() if p is not None else None
    if move_dir is None or move_dir == Direction.CENTRE:
        _debug_bridge(c, "walk_no_dstar_step", f"cur=({self.current_pos.x},{self.current_pos.y}) target=({target.x},{target.y})")
        key = ("bridge_walk", self.current_pos.x, self.current_pos.y, target.x, target.y)
        _bridge_fail(self, c, key, "walk_no_dstar_step")
        return True

    if not _can_execute_bridge_walk_step(c, move_dir):
        _debug_bridge(c, "walk_dstar_step_blocked", f"dir={move_dir} cur=({self.current_pos.x},{self.current_pos.y})")
        key = ("bridge_walk", self.current_pos.x, self.current_pos.y, target.x, target.y)
        _bridge_fail(self, c, key, "walk_dstar_step_blocked", f"dir={move_dir}")
        return True

    move_pos = self.current_pos.add(move_dir)
    build_id = c.get_tile_building_id(move_pos)
    if build_id is not None and c.get_entity_type(build_id) == EntityType.MARKER and c.can_destroy(move_pos):
        _debug_bridge(c, "walk_destroy_marker", f"pos=({move_pos.x},{move_pos.y})")
        c.destroy(move_pos)
        return True

    tile_env_before = c.get_tile_env(move_pos)
    road_built = False
    # Only build a road when can_move is False (e.g. water tile needing a road to cross).
    # Empty land tiles are directly walkable; building a road on them is unnecessary.
    if not c.can_move(move_dir) and c.can_build_road(move_pos):
        _debug_bridge(c, "walk_build_road", f"pos=({move_pos.x},{move_pos.y})")
        c.build_road(move_pos)
        road_built = True

    bid_before = c.get_tile_building_id(move_pos)
    can_mv = c.can_move(move_dir)
    _debug_bridge(c, "walk_pre_move_check", f"dir={move_dir} to=({move_pos.x},{move_pos.y}) can_move={can_mv} env={tile_env_before} road_built={road_built} building={c.get_entity_type(bid_before) if bid_before is not None else None}")

    if can_mv:
        _debug_bridge(c, "walk_move", f"dir={move_dir} to=({move_pos.x},{move_pos.y})")
        c.move(move_dir)
    else:
        key = (self.current_pos.x, self.current_pos.y, move_pos.x, move_pos.y)
        reason = "walk_stuck_replan"
        extra = f"dir={move_dir} to=({move_pos.x},{move_pos.y}) env={tile_env_before}"
        if bid_before is not None and c.get_entity_type(bid_before) in _BRIDGE_WALKABLE_TYPES:
            reason = "walk_stuck_replan_walkable_blocked"
            extra = f"type={c.get_entity_type(bid_before)}"
        else:
            _debug_bridge(c, "walk_cannot_move_after_prep", extra)
        _bridge_fail(self, c, key, reason, extra)
    return True


def _build_return_step(self: Harvester, c: Controller) -> bool:
    if self.bridge_jump_target is not None:
        return _walk_toward_bridge_target(self, c)

    if self.just_placed:
        move_pos = self.current_pos
        if self.harvester_pos and is_diagonal(self.current_pos, self.harvester_pos):
            ns, ew = split_diagonal(self.current_pos, self.harvester_pos)
            m1 = self.current_pos.add(ns)  # type: ignore
            m2 = self.current_pos.add(ew)  # type: ignore
            move_pos = m1 if m1.distance_squared(self.core_pos) < m2.distance_squared(self.core_pos) else m2

        build_id = c.get_tile_building_id(move_pos)
        if build_id is not None and c.get_entity_type(build_id) in {EntityType.ROAD, EntityType.CONVEYOR} and c.can_destroy(move_pos):
            c.destroy(move_pos)

        step = _planner_step_at(self, c, move_pos) or move_pos.direction_to(self.core_pos)
        if step is None or step == Direction.CENTRE:
            return False
        if step not in DIRECTIONS_4:
            step = get_direction_4(move_pos, self.core_pos)
            if step is None:
                return False

        if c.get_tile_building_id(move_pos) is None:
            conveyor_cost_ti, _ = c.get_conveyor_cost()
            if self.ti < conveyor_cost_ti:
                return False
        if c.can_build_conveyor(move_pos, step):
            c.build_conveyor(move_pos, step)

        step_dir = get_direction_4(self.current_pos, move_pos) if self.current_pos != move_pos else None
        if step_dir and not c.can_move(step_dir):
            return False
        self.just_placed = False
        self.return_next_dir = step
        if step_dir:
            c.move(step_dir)
        return True

    planner = _ensure_return_planner(self, c)
    planner_step: Direction | None = None
    if planner is not None:
        planner.set_position(self.current_pos.x, self.current_pos.y)

        step_xy = planner.step_xy()
        if step_xy is not None:
            cx, cy = self.current_pos.x, self.current_pos.y
            tx, ty = step_xy
            dsq = (tx - cx) * (tx - cx) + (ty - cy) * (ty - cy)
            if dsq > 1:
                return _handle_bridge_jump(self, c, Position(tx, ty))
            planner_step = self.current_pos.direction_to(Position(tx, ty))

    if self.return_next_dir is not None:
        move_dir = self.return_next_dir
        self.return_next_dir = None
    else:
        move_dir = planner_step
        if move_dir is None or move_dir == Direction.CENTRE:
            move_dir = self.current_pos.direction_to(self.core_pos)
        if move_dir is None or move_dir == Direction.CENTRE:
            return False

    next_dir = _next_dir_after_move(self, c, move_dir)

    move_pos = self.current_pos.add(move_dir)

    if _try_join_axionite_to_titanium_chain(self, c, move_pos):
        return True

    if next_dir is not None:
        bid = c.get_tile_building_id(move_pos)
        if (
            bid is not None
            and c.get_entity_type(bid) == EntityType.CONVEYOR
            and c.get_team(bid) == c.get_team()
            and c.get_direction(bid) != next_dir
            and c.can_destroy(move_pos)
        ):
            c.destroy(move_pos)
            return False

    build_id = c.get_tile_building_id(move_pos)
    if reached_core(move_pos, self.core_pos) or (
        build_id is not None and c.get_entity_type(build_id) == EntityType.CORE
    ):
        if not c.can_move(move_dir):
            return False
        c.move(move_dir)
        return True

    if _enemy_walkable_at(c, move_pos):
        if not c.can_move(move_dir):
            return False
        self.return_next_dir = next_dir
        c.move(move_dir)
        return True

    if not c.can_move(move_dir):
        can_execute = False
        if c.get_tile_env(move_pos) == Environment.EMPTY:
            bid = c.get_tile_building_id(move_pos)
            if bid is not None and c.get_entity_type(bid) == EntityType.MARKER:
                can_execute = True
            elif c.can_build_road(move_pos):
                can_execute = True
            elif next_dir is not None:
                can_execute = c.can_build_conveyor(move_pos, next_dir)
        if not can_execute:
            return False

    if not _clear_return_tile(self, c, move_pos):
        return False

    dest_empty = c.get_tile_env(move_pos) == Environment.EMPTY
    if next_dir is not None:
        if dest_empty:
            conveyor_cost_ti, _ = c.get_conveyor_cost()
            if self.ti < conveyor_cost_ti:
                return False
        if c.can_build_conveyor(move_pos, next_dir):
            c.build_conveyor(move_pos, next_dir)
    elif dest_empty and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if not c.can_move(move_dir):
        return False
    self.return_next_dir = next_dir
    c.move(move_dir)
    return True
