from cambc import Controller, EntityType, Position

_PRIORITY = (
    EntityType.BUILDER_BOT,
    EntityType.FOUNDRY,
    EntityType.CORE,
    EntityType.BARRIER,
)


class Sentinel:
    def __init__(self):
        pass

    def run(self, c: Controller):
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
            d2 = my_pos.distance_squared(pos)
            cur = best[tier]
            if cur is None or d2 < cur[1]:
                best[tier] = (pos, d2)

        for cur in best:
            if cur is not None:
                c.fire(cur[0])
                return
