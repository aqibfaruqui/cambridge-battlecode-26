from cambc import Controller, EntityType, Position, Environment
from utils.pathfinding.movement import DIRECTIONS_8

_PRIORITY = (
    EntityType.BUILDER_BOT,
    EntityType.LAUNCHER,
    EntityType.BREACH,
    EntityType.SENTINEL,
    EntityType.GUNNER,
    EntityType.FOUNDRY,
    EntityType.CORE,
    EntityType.BARRIER,
    EntityType.CONVEYOR,
)
_FIRE_TYPES = frozenset(_PRIORITY)


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
        if target is not None and self._is_enemy_priority(c, target, my_team):
            if c.can_fire(target):
                c.fire(target)
                c.draw_indicator_dot(my_pos, 200, 0, 255)
                c.draw_indicator_line(my_pos, target, 200, 0, 255)
                return

        # No worthwhile target ahead: rotate toward the best-priority enemy
        # sitting on one of the 8 rays from this tile.
        best: list[tuple[Position, int] | None] = [None] * len(_PRIORITY)
        for dir in DIRECTIONS_8:
            for dist in range(1, 4):
                target = my_pos 
                for _ in range(dist):
                    target = target.add(dir)

                if not c.is_in_vision(target):
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

                if bid is not None and c.get_team(bid) == my_team:
                    break
                elif bid is not None:
                    etype = c.get_entity_type(bid)
                    if etype in _FIRE_TYPES and etype not in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
                        priority = _PRIORITY.index(etype)
                        best[priority] = (target, dist)
                    elif etype in {EntityType.CONVEYOR, EntityType.ARMOURED_CONVEYOR}:
                        if c.get_direction(bid) != target.direction_to(c.get_position()):
                            priority = _PRIORITY.index(EntityType.CONVEYOR)
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
