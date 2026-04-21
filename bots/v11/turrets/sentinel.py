from cambc import Controller, EntityType, Position

from turrets.resource_trace import feeds_friendly_turret

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
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
)

_RELAY_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.ARMOURED_CONVEYOR,
    EntityType.BRIDGE,
    EntityType.SPLITTER,
})


class Sentinel:
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

        # Best (closest) targetable position per priority tier.
        best: list[tuple[Position, int] | None] = [None] * len(_PRIORITY)
        for eid in c.get_nearby_entities():
            if c.get_team(eid) == my_team:
                continue
            et = c.get_entity_type(eid)
            try:
                tier = _PRIORITY.index(et)
            except ValueError:
                continue
            pos = c.get_position(eid)
            if not c.can_fire(pos):
                continue
            if et in _RELAY_TYPES and feeds_friendly_turret(c, pos, my_team):
                continue

            bb = c.get_tile_builder_bot_id(pos)
            if bb is not None and c.get_team(bb) == my_team:
                continue
            d2 = my_pos.distance_squared(pos)
            cur = best[tier]
            if cur is None or d2 < cur[1]:
                best[tier] = (pos, d2)

        for cur in best:
            if cur is not None:
                c.fire(cur[0])
                return
