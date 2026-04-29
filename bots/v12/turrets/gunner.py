from cambc import Controller, Direction, EntityType, Position, Environment, ResourceType
from utils.pathfinding.movement import DIRECTIONS_8
from turrets.resource_trace import feeds_friendly_turret

_PRIORITY = (
    EntityType.BUILDER_BOT,
    EntityType.LAUNCHER,
    EntityType.BREACH,
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.FOUNDRY,
    EntityType.CORE,
    EntityType.MARKER,
    EntityType.BARRIER,
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
)
_FIRE_TYPES = frozenset(_PRIORITY)
_RELAY_TYPES = frozenset(
    {
        EntityType.CONVEYOR,
        EntityType.ARMOURED_CONVEYOR,
        EntityType.BRIDGE,
        EntityType.SPLITTER,
    }
)
_CARDINAL = (
    Direction.NORTH,
    Direction.EAST,
    Direction.SOUTH,
    Direction.WEST,
)
_GUNNER_RANGE_SQ = 13


class Gunner:
    def __init__(self):
        self.empty_rounds = 0

    def run(self, c: Controller):
        if c.get_ammo_amount() == 0:
            self.empty_rounds += 1
            if self.empty_rounds > 50:
                c.self_destruct()
                return
        else:
            self.empty_rounds = 0

        my_team = c.get_team()
        my_pos = c.get_position()

        target = c.get_gunner_target()
        enemy_core = self._enemy_core_ahead(c, my_pos, c.get_direction(), my_team)
        if enemy_core is not None:
            target = enemy_core if c.can_fire(enemy_core) else target
            if (
                target is not None
                and not self._is_friendly_titanium_source(c, target, my_team)
                and c.can_fire(target)
            ):
                c.fire(target)
                c.draw_indicator_dot(my_pos, 255, 0, 0)
                c.draw_indicator_line(my_pos, enemy_core, 255, 0, 0)
                return

        if target is not None and self._is_enemy_priority(c, target, my_team):
            if c.can_fire(target):
                c.fire(target)
                c.draw_indicator_dot(my_pos, 200, 0, 255)
                c.draw_indicator_line(my_pos, target, 200, 0, 255)
                return

        if target is not None and self._is_friendly_destroyable(c, target, my_team):
            if c.can_fire(target):
                c.fire(target)
                c.draw_indicator_dot(my_pos, 100, 100, 100)
                c.draw_indicator_line(my_pos, target, 100, 100, 100)
                return

        # No worthwhile target ahead: rotate toward the best-priority enemy
        # sitting on one of the 8 rays from this tile.
        best: list[tuple[Position, int] | None] = [None] * len(_PRIORITY)
        for dir in DIRECTIONS_8:
            for dist in range(1, 4):
                target = my_pos
                for _ in range(dist):
                    target = target.add(dir)

                if (
                    not c.is_in_vision(target)
                    or target.x < 0
                    or target.y < 0
                    or target.x >= c.get_map_width()
                    or target.y >= c.get_map_height()
                ):
                    break

                if c.get_tile_env(target) == Environment.WALL:
                    break

                bid = c.get_tile_building_id(target)
                builder = c.get_tile_builder_bot_id(target)
                if builder is not None and c.get_team(builder) != my_team:
                    etype = c.get_entity_type(builder)
                    if etype in _FIRE_TYPES:
                        priority = _PRIORITY.index(etype)
                        best[priority] = (target, dist)
                    break
                elif builder is not None:
                    break

                if bid is not None and c.get_team(bid) == my_team:
                    etype = c.get_entity_type(bid)
                    if etype == EntityType.MARKER:
                        best[_PRIORITY.index(EntityType.MARKER)] = (target, dist)
                    elif etype in _RELAY_TYPES:
                        if not feeds_friendly_turret(c, target, my_team):
                            best[_PRIORITY.index(etype)] = (target, dist)
                    break
                elif bid is not None:
                    etype = c.get_entity_type(bid)
                    if etype in _RELAY_TYPES:
                        if not feeds_friendly_turret(c, target, my_team):
                            priority = _PRIORITY.index(etype)
                            best[priority] = (target, dist)
                    elif etype in _FIRE_TYPES:
                        priority = _PRIORITY.index(etype)
                        best[priority] = (target, dist)
                    break

        for cur in best:
            if cur is None:
                continue
            target_pos, _ = cur
            direction = my_pos.direction_to(target_pos)
            if c.can_rotate(direction):
                c.rotate(direction)
                c.draw_indicator_line(my_pos, target_pos, 255, 128, 0)
            return

    def _is_enemy_priority(self, c: Controller, pos: Position, my_team) -> bool:
        eid = c.get_tile_builder_bot_id(pos)
        if eid is None:
            eid = c.get_tile_building_id(pos)
        if eid is None:
            return False
        if c.get_team(eid) == my_team:
            return False
        return c.get_entity_type(eid) in _FIRE_TYPES

    def _is_friendly_destroyable(self, c: Controller, pos: Position, my_team) -> bool:
        if c.get_tile_builder_bot_id(pos) is not None:
            return False
        bid = c.get_tile_building_id(pos)
        if bid is None:
            return False
        if c.get_team(bid) != my_team:
            return False
        etype = c.get_entity_type(bid)
        if etype == EntityType.MARKER:
            return True
        return False

    def _enemy_core_ahead(
        self,
        c: Controller,
        my_pos: Position,
        direction: Direction,
        my_team,
    ) -> Position | None:
        if direction == Direction.CENTRE:
            return None

        pos = my_pos.add(direction)
        while my_pos.distance_squared(pos) <= _GUNNER_RANGE_SQ:
            if (
                pos.x < 0
                or pos.y < 0
                or pos.x >= c.get_map_width()
                or pos.y >= c.get_map_height()
                or not c.is_in_vision(pos)
            ):
                return None

            if c.get_tile_env(pos) == Environment.WALL:
                return None

            bid = c.get_tile_building_id(pos)
            if (
                bid is not None
                and c.get_team(bid) != my_team
                and c.get_entity_type(bid) == EntityType.CORE
            ):
                return pos

            pos = pos.add(direction)

        return None

    def _is_friendly_titanium_source(
        self,
        c: Controller,
        pos: Position,
        my_team,
    ) -> bool:
        bid = c.get_tile_building_id(pos)
        if bid is None or c.get_team(bid) != my_team:
            return False
        etype = c.get_entity_type(bid)
        if etype not in _RELAY_TYPES:
            return False
        if c.get_stored_resource(bid) == ResourceType.TITANIUM:
            return True
        return self._titanium_reaches(c, pos, my_team)

    def _flows_into(
        self,
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
        for out_dir in out_dirs:
            out = pred_pos.add(out_dir)
            if out.x == target.x and out.y == target.y:
                return True
        return False

    def _titanium_reaches(self, c: Controller, target: Position, my_team) -> bool:
        bridges_by_exit: dict[tuple[int, int], list[int]] = {}
        for bid in c.get_nearby_buildings():
            if c.get_team(bid) != my_team or c.get_entity_type(bid) != EntityType.BRIDGE:
                continue
            exit_pos = c.get_bridge_target(bid)
            bridges_by_exit.setdefault((exit_pos.x, exit_pos.y), []).append(bid)

        visited: set[tuple[int, int]] = set()
        stack: list[Position] = [target]
        while stack:
            pos = stack.pop()
            key = (pos.x, pos.y)
            if key in visited:
                continue
            visited.add(key)

            for direction in _CARDINAL:
                pred = pos.add(direction)
                if (
                    pred.x < 0
                    or pred.y < 0
                    or pred.x >= c.get_map_width()
                    or pred.y >= c.get_map_height()
                    or not c.is_in_vision(pred)
                ):
                    continue
                pred_id = c.get_tile_building_id(pred)
                if pred_id is None or c.get_team(pred_id) != my_team:
                    continue
                etype = c.get_entity_type(pred_id)
                if etype not in _RELAY_TYPES or etype == EntityType.BRIDGE:
                    continue
                if not self._flows_into(c, pred, pred_id, etype, pos):
                    continue
                if c.get_stored_resource(pred_id) == ResourceType.TITANIUM:
                    return True
                stack.append(pred)

            for bridge_id in bridges_by_exit.get(key, ()):
                if c.get_stored_resource(bridge_id) == ResourceType.TITANIUM:
                    return True
                stack.append(c.get_position(bridge_id))

        return False
