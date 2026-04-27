from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, Direction, EntityType, Environment, Position

from utils.assassin_states import AssassinState
from utils.pathfinding.d_star import DStarLite, _SEEK_BLOCK_MASK
from utils.pathfinding.movement import DIRECTIONS_4, get_direction_4

if TYPE_CHECKING:
    from builders.assassin import Assassin


# Enemy buildings we can walk on — we step onto them then fire from underneath
# to clear the tile. Notably excludes HARVESTER (cannot be fired on).
_ENEMY_WALKABLE_TYPES = (
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
    EntityType.ROAD,
)
_MAX_BRIDGE_FAILS = 3


def attack(self: Assassin, c: Controller) -> None:
    assert self.target_ore is not None
    assert self.target_stand_pos is not None
    assert self.target_gunner_pos is not None
    assert self.enemy_core_pos is not None

    if not self.harvester_built:
        _resolve_harvester(self, c)
        return

    gp = self.target_gunner_pos

    # "Reached" condition: cardinally adjacent to the gunner tile and not
    # mid-bridge — analogous to harvester's reached_core check that exits RETURN.
    if _is_cardinal_adjacent(self.current_pos, gp) and self.bridge_jump_target is None:
        if _try_place_gunner(self, c, gp):
            return

    if _attack_enemy_under_bot(self, c):
        return

    if _handle_post_bridge_conveyor(self, c):
        return

    _build_pipeline_step(self, c)


# ---------- harvester acquisition (phase-driven, mirrors placing_harvester) ----------

_HARVEST_DECIDE = "decide"
_HARVEST_STEP_ON = "step_on"
_HARVEST_RING = "ring"
_HARVEST_STEP_OFF = "step_off"
_HARVEST_BUILD = "build"

# Cap turns spent ringing so a permanently-blocked side can't strand us on the ore.
_RING_TURN_CAP = 8


def _resolve_harvester(self: Assassin, c: Controller) -> None:
    """Drive the placement state machine through to a built/adopted harvester."""
    if self.harvest_phase == _HARVEST_DECIDE:
        _harvest_decide(self, c)
    elif self.harvest_phase == _HARVEST_STEP_ON:
        _harvest_step_on(self, c)
    elif self.harvest_phase == _HARVEST_RING:
        _harvest_ring(self, c)
    elif self.harvest_phase == _HARVEST_STEP_OFF:
        _harvest_step_off(self, c)
    elif self.harvest_phase == _HARVEST_BUILD:
        _harvest_build(self, c)
    else:
        _abandon_ore(self)


def _harvest_decide(self: Assassin, c: Controller) -> None:
    """Inspect the ore tile and pick the next phase (or abandon)."""
    ore = self.target_ore
    assert ore is not None
    bid = c.get_tile_building_id(ore)

    if bid is None:
        self.harvest_phase = _HARVEST_STEP_ON
        return

    et = c.get_entity_type(bid)

    # Markers don't block — proceed with the placement sequence and
    # `_harvest_build` will tear the marker down before building.
    if et == EntityType.MARKER:
        self.harvest_phase = _HARVEST_STEP_ON
        return

    if c.get_team(bid) == c.get_team():
        if et == EntityType.HARVESTER:
            _adopt_existing_harvester(self)
            return
        if c.can_destroy(ore):
            c.destroy(ore)
        return

    # Enemy occupant.
    if et == EntityType.HARVESTER:
        # Can't fire on enemy harvester — siphon via the chain.
        _adopt_existing_harvester(self)
        return

    if et in _ENEMY_WALKABLE_TYPES:
        # Step onto the ore; `_harvest_step_on` will fire-clear from on top.
        self.harvest_phase = _HARVEST_STEP_ON
        return

    # Enemy turret — abandon.
    _abandon_ore(self)


def _adopt_existing_harvester(self: Assassin) -> None:
    """Skip placement (and the ring) — an existing harvester feeds the chain."""
    self.harvester_built = True
    self.just_placed = True
    self.harvest_phase = _HARVEST_DECIDE
    self.harvest_sides_pending = []
    self.harvest_ring_turns = 0


def _abandon_ore(self: Assassin) -> None:
    if self.target_ore is not None:
        self.ore_blacklist.add((self.target_ore.x, self.target_ore.y))
    self.target_ore = None
    self.target_stand_pos = None
    self.target_gunner_pos = None
    self.harvest_phase = _HARVEST_DECIDE
    self.harvest_sides_pending = []
    self.harvest_ring_turns = 0
    self._planner = None
    self._planner_goal = None
    self._state = AssassinState.FIND_ORE


def _harvest_step_on(self: Assassin, c: Controller) -> None:
    """Walk onto the ore. If it's an enemy walkable, fire from on top to clear it."""
    ore = self.target_ore
    stand = self.target_stand_pos
    assert ore is not None and stand is not None

    if self.current_pos == ore:
        if _enemy_walkable_at(c, ore):
            if c.can_fire(ore):
                c.fire(ore)
            return
        # Tile is clear — start ringing the non-stand sides.
        stand_side = ore.direction_to(stand)
        self.harvest_sides_pending = [d for d in DIRECTIONS_4 if d != stand_side]
        self.harvest_ring_turns = 0
        self.harvest_phase = _HARVEST_RING
        return

    move_dir = self.current_pos.direction_to(ore)
    if move_dir not in DIRECTIONS_4:
        _abandon_ore(self)
        return
    if c.can_move(move_dir):
        c.move(move_dir)


def _harvest_ring(self: Assassin, c: Controller) -> None:
    """Build barrier conveyors on every side of the ore except the stand_pos side."""
    ore = self.target_ore
    assert ore is not None

    if self.current_pos != ore:
        # Knocked off — return and try again.
        self.harvest_phase = _HARVEST_STEP_ON
        return

    self.harvest_ring_turns += 1
    built = False
    remaining: list[Direction] = []
    for side in self.harvest_sides_pending:
        if built:
            remaining.append(side)
            continue
        side_pos = ore.add(side)
        flow = side.opposite()  # barrier conveyors flow toward the ore, like do_ring
        bid = c.get_tile_building_id(side_pos)
        if (
            bid is not None
            and c.get_entity_type(bid) in {EntityType.MARKER, EntityType.ROAD}
            and c.can_destroy(side_pos)
            and c.get_global_resources()[0] >= c.get_conveyor_cost()[0]
        ):
            c.destroy(side_pos)
        if c.can_build_conveyor(side_pos, flow):
            c.build_conveyor(side_pos, flow)
            built = True
    self.harvest_sides_pending = remaining

    if not self.harvest_sides_pending or self.harvest_ring_turns >= _RING_TURN_CAP:
        self.harvest_phase = _HARVEST_STEP_OFF


def _harvest_step_off(self: Assassin, c: Controller) -> None:
    """Walk back to stand_pos so we can build the harvester from there."""
    stand = self.target_stand_pos
    assert stand is not None
    if self.current_pos == stand:
        self.harvest_phase = _HARVEST_BUILD
        return
    move_dir = self.current_pos.direction_to(stand)
    if move_dir not in DIRECTIONS_4:
        _abandon_ore(self)
        return
    if c.can_move(move_dir):
        c.move(move_dir)


def _harvest_build(self: Assassin, c: Controller) -> None:
    """From stand_pos, place the harvester on the ore and prime the chain."""
    ore = self.target_ore
    stand = self.target_stand_pos
    assert ore is not None and stand is not None

    if self.current_pos != stand:
        self.harvest_phase = _HARVEST_STEP_OFF
        return

    bid = c.get_tile_building_id(ore)
    if (
        bid is not None
        and c.get_entity_type(bid) in {EntityType.ROAD, EntityType.CONVEYOR, EntityType.MARKER}
        and c.can_destroy(ore)
        and c.get_global_resources()[0] >= c.get_harvester_cost()[0]
    ):
        c.destroy(ore)
        return

    if not c.can_build_harvester(ore):
        return

    c.build_harvester(ore)
    self.harvester_built = True
    self.just_placed = True
    self.harvest_phase = _HARVEST_DECIDE
    self.harvest_sides_pending = []
    self.harvest_ring_turns = 0


# ---------- pipeline-step primitives (mirror of _build_return_step) ----------

def _build_pipeline_step(self: Assassin, c: Controller) -> None:
    gp = self.target_gunner_pos
    assert gp is not None

    if self.bridge_jump_target is not None:
        _walk_toward_bridge_target(self, c)
        return

    if self.just_placed:
        _do_just_placed(self, c, gp)
        return

    planner = _ensure_pipeline_planner(self, c)
    planner_step: Direction | None = None
    if planner is not None:
        planner.set_position(self.current_pos.x, self.current_pos.y)
        step_xy = planner.step_xy()
        if step_xy is not None:
            cx, cy = self.current_pos.x, self.current_pos.y
            tx, ty = step_xy
            dsq = (tx - cx) * (tx - cx) + (ty - cy) * (ty - cy)
            if dsq > 1:
                _handle_bridge_jump(self, c, Position(tx, ty))
                return
            planner_step = self.current_pos.direction_to(Position(tx, ty))

    if self.return_next_dir is not None:
        move_dir = self.return_next_dir
        self.return_next_dir = None
    else:
        move_dir = planner_step
        if move_dir is None or move_dir == Direction.CENTRE:
            move_dir = self.current_pos.direction_to(gp)
        if move_dir is None or move_dir == Direction.CENTRE:
            return

    next_dir = _next_dir_after_move(self, c, move_dir)
    move_pos = self.current_pos.add(move_dir)

    # Wrong-direction friendly conveyor at the next tile: tear down so we can
    # rebuild it pointing the right way next tick.
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
            return

    # Stepping onto gunner_pos itself — place the gunner instead of moving.
    if move_pos == gp:
        _try_place_gunner(self, c, gp)
        return

    if _enemy_walkable_at(c, move_pos):
        if not c.can_move(move_dir):
            return
        self.return_next_dir = next_dir
        c.move(move_dir)
        return

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
            return

    if not _clear_pipeline_tile(c, move_pos):
        return

    dest_empty = c.get_tile_env(move_pos) == Environment.EMPTY
    if next_dir is not None:
        if dest_empty:
            ti, _ = c.get_global_resources()
            if ti < c.get_conveyor_cost()[0]:
                return
        if c.can_build_conveyor(move_pos, next_dir):
            c.build_conveyor(move_pos, next_dir)
    elif dest_empty and c.can_build_road(move_pos):
        c.build_road(move_pos)

    if not c.can_move(move_dir):
        return
    self.return_next_dir = next_dir
    c.move(move_dir)


def _do_just_placed(self: Assassin, c: Controller, gp: Position) -> None:
    """First conveyor of the chain — sits cardinally adjacent to the harvester."""
    move_pos = self.current_pos

    # Tear down any road/conveyor we paved while walking here so we can place
    # a fresh conveyor pointing forward.
    bid = c.get_tile_building_id(move_pos)
    if (
        bid is not None
        and c.get_entity_type(bid) in {EntityType.ROAD, EntityType.CONVEYOR}
        and c.can_destroy(move_pos)
    ):
        c.destroy(move_pos)

    step = _planner_step_at(self, c, move_pos)
    if step is None or step == Direction.CENTRE:
        step = move_pos.direction_to(gp)
    if step is None or step == Direction.CENTRE:
        return
    if step not in DIRECTIONS_4:
        step = get_direction_4(move_pos, gp)
        if step is None:
            return

    if c.get_tile_building_id(move_pos) is None:
        ti, _ = c.get_global_resources()
        if ti < c.get_conveyor_cost()[0]:
            return
    if c.can_build_conveyor(move_pos, step):
        c.build_conveyor(move_pos, step)
        self.just_placed = False
        self.return_next_dir = step


# ---------- post-bridge / under-bot helpers (mirrors of return_to_core) ----------

def _attack_enemy_under_bot(self: Assassin, c: Controller) -> bool:
    if not _enemy_walkable_at(c, self.current_pos):
        return False
    if c.can_fire(self.current_pos):
        c.fire(self.current_pos)
        if c.get_tile_building_id(self.current_pos) is None:
            self.post_bridge_conveyor = True
    return True


def _handle_post_bridge_conveyor(self: Assassin, c: Controller) -> bool:
    """Place a conveyor on the current tile after a bridge crossing or fire-clear."""
    if not self.post_bridge_conveyor:
        return False

    gp = self.target_gunner_pos
    assert gp is not None

    if _is_cardinal_adjacent(self.current_pos, gp):
        # No conveyor needed — gunner placement handles this in attack().
        self.post_bridge_conveyor = False
        return True

    conveyor_dir = _planner_step_at(self, c, self.current_pos)
    if conveyor_dir is None or conveyor_dir == Direction.CENTRE or conveyor_dir not in DIRECTIONS_4:
        conveyor_dir = get_direction_4(self.current_pos, gp)
    if conveyor_dir is None:
        self.post_bridge_conveyor = False
        return False

    bid = c.get_tile_building_id(self.current_pos)
    if (
        bid is not None
        and c.get_entity_type(bid) == EntityType.CONVEYOR
        and c.get_team(bid) == c.get_team()
        and c.get_direction(bid) != conveyor_dir
        and c.can_destroy(self.current_pos)
    ):
        c.destroy(self.current_pos)
        return True

    if _clear_pipeline_tile(c, self.current_pos):
        tile_empty = c.get_tile_env(self.current_pos) == Environment.EMPTY
        ti, _ = c.get_global_resources()
        conveyor_cost_ti, _ = c.get_conveyor_cost()
        if not tile_empty or ti >= conveyor_cost_ti:
            if tile_empty and c.can_build_conveyor(self.current_pos, conveyor_dir):
                c.build_conveyor(self.current_pos, conveyor_dir)
                self.return_next_dir = conveyor_dir
            self.post_bridge_conveyor = False

    return True


def _next_dir_after_move(self: Assassin, c: Controller, move_dir: Direction) -> Direction | None:
    """Cardinal direction the conveyor at the tile we step onto should point."""
    move_pos = self.current_pos.add(move_dir)
    follow_dir = _planner_step_at(self, c, move_pos) or move_pos.direction_to(self.target_gunner_pos)  # type: ignore[arg-type]
    if follow_dir is None or follow_dir == Direction.CENTRE:
        return None
    if follow_dir in DIRECTIONS_4:
        return follow_dir
    return get_direction_4(move_pos, move_pos.add(follow_dir))


# ---------- bridge handling (mirror of return_to_core) ----------

def _handle_bridge_jump(self: Assassin, c: Controller, target: Position) -> None:
    """Build a bridge to `target`, then walk across it."""
    bridge_pos = self.current_pos
    my_team = c.get_team()

    if self.bridge_jump_target is not None:
        _walk_toward_bridge_target(self, c)
        return

    bid = c.get_tile_building_id(bridge_pos)
    if bid is not None and c.get_entity_type(bid) == EntityType.BRIDGE and c.get_team(bid) == my_team:
        self.bridge_jump_target = target
        _walk_toward_bridge_target(self, c)
        return

    et = c.get_entity_type(bid) if bid is not None else None
    if (
        bid is not None
        and et in (EntityType.ROAD, EntityType.CONVEYOR)
        and c.get_team(bid) == my_team
        and c.can_destroy(bridge_pos)
    ):
        ti, _ = c.get_global_resources()
        if ti < c.get_bridge_cost()[0]:
            return
        c.destroy(bridge_pos)
        if c.can_build_bridge(bridge_pos, target):
            c.build_bridge(bridge_pos, target)
            self.bridge_jump_target = target
        return

    if c.can_build_bridge(bridge_pos, target):
        c.build_bridge(bridge_pos, target)
        self.bridge_jump_target = target
        return

    ti, _ = c.get_global_resources()
    if ti >= c.get_bridge_cost()[0]:
        key = (bridge_pos.x, bridge_pos.y, target.x, target.y)
        fails = self.bridge_fail_counts.get(key, 0) + 1
        self.bridge_fail_counts[key] = fails
        if fails >= _MAX_BRIDGE_FAILS:
            self._planner = None
            self._planner_goal = None
            self.bridge_fail_counts.pop(key, None)


def _walk_toward_bridge_target(self: Assassin, c: Controller) -> None:
    target = self.bridge_jump_target
    if target is None:
        return

    if self.current_pos == target:
        self.bridge_jump_target = None
        self.bridge_target_planner = None
        self.post_bridge_conveyor = True
        return

    if self.bridge_target_planner is None:
        self.bridge_target_planner = DStarLite(
            self._env_map, target.x, target.y,
            block_mask=_SEEK_BLOCK_MASK,
        )
    p = self.bridge_target_planner
    p.set_position(self.current_pos.x, self.current_pos.y)
    p.set_dynamic_blockers(_pipeline_blockers(c))
    p.notify_map_changes()
    d = p.step()
    if d is None or d == Direction.CENTRE:
        d = self.current_pos.direction_to(target)
    if d is None or d == Direction.CENTRE:
        self.bridge_jump_target = None
        self.bridge_target_planner = None
        self.post_bridge_conveyor = True
        return

    next_pos = self.current_pos.add(d)
    if c.can_build_road(next_pos):
        c.build_road(next_pos)
    if c.can_move(d):
        c.move(d)


# ---------- low-level helpers ----------

def _ensure_pipeline_planner(self: Assassin, c: Controller) -> DStarLite:
    """D* with bridges enabled, goal = gunner_pos. Refreshes blockers each call."""
    gp = self.target_gunner_pos
    assert gp is not None
    goal = (gp.x, gp.y)
    if (
        self._planner is None
        or self._planner_goal != goal
        or not self._planner_use_bridges
    ):
        self._planner = DStarLite(
            self._env_map, gp.x, gp.y,
            block_mask=_SEEK_BLOCK_MASK,
            use_bridges=True,
        )
        self._planner_goal = goal
        self._planner_use_bridges = True
    self._planner.set_dynamic_blockers(_pipeline_blockers(c))
    self._planner.notify_map_changes()
    return self._planner


def _planner_step_at(self: Assassin, c: Controller, pos: Position) -> Direction | None:
    p = _ensure_pipeline_planner(self, c)
    p.set_position(pos.x, pos.y)
    step = p.step()
    return None if step == Direction.CENTRE else step


def _pipeline_blockers(c: Controller) -> list[tuple[int, int]]:
    """Block enemy/own buildings except markers (we build through them) and
    other bots; mirrors `_return_dynamic_blockers` from harvester."""
    team = c.get_team()
    blockers: list[tuple[int, int]] = []
    for pos in c.get_nearby_tiles():
        bid = c.get_tile_building_id(pos)
        if bid is None:
            continue
        et = c.get_entity_type(bid)
        if et == EntityType.MARKER:
            continue
        if et == EntityType.HARVESTER or c.get_team(bid) != team:
            blockers.append((pos.x, pos.y))
    return blockers


def _try_place_gunner(self: Assassin, c: Controller, pos: Position) -> bool:
    ec = self.enemy_core_pos
    assert ec is not None
    facing = pos.direction_to(ec)
    if facing is None or facing == Direction.CENTRE:
        return False
    bid = c.get_tile_building_id(pos)
    if bid is not None:
        # Clear our own non-marker buildings (markers don't block placement).
        if c.get_entity_type(bid) == EntityType.MARKER:
            pass
        elif c.get_team(bid) == c.get_team() and c.can_destroy(pos):
            c.destroy(pos)
            return False
        else:
            return False
    if not c.can_build_gunner(pos, facing):
        return False
    c.build_gunner(pos, facing)
    self.gunner_built = True
    self._state = AssassinState.PATROL
    return True


def _clear_pipeline_tile(c: Controller, pos: Position) -> bool:
    """Mirror of `_clear_return_tile`: markers/cores pass through, our roads
    get destroyed-and-cleared, our conveyor/bridge/splitter is acceptable."""
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return True
    et = c.get_entity_type(bid)
    if et in (EntityType.MARKER, EntityType.CORE):
        return True
    if et == EntityType.ROAD:
        if c.can_destroy(pos):
            c.destroy(pos)
            return True
        return False
    if c.get_team(bid) != c.get_team():
        return False
    return et in (EntityType.CONVEYOR, EntityType.SPLITTER, EntityType.BRIDGE)


def _enemy_walkable_at(c: Controller, pos: Position) -> bool:
    bid = c.get_tile_building_id(pos)
    if bid is None:
        return False
    if c.get_team(bid) == c.get_team():
        return False
    return c.get_entity_type(bid) in _ENEMY_WALKABLE_TYPES


def _is_cardinal_adjacent(a: Position, b: Position) -> bool:
    return abs(a.x - b.x) + abs(a.y - b.y) == 1
