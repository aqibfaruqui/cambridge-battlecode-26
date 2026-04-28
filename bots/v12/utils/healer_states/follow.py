from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType

from utils.defense.combat import (
    VISION_RADIUS_SQ,
    find_enemy_pos,
    step_toward,
)

if TYPE_CHECKING:
    from builders.healer import Healer


def _pick_closest_enemy_builder(c: Controller) -> int | None:
    me = c.get_position()
    my_team = c.get_team()
    best_id: int | None = None
    best_d = VISION_RADIUS_SQ + 1
    for uid in c.get_nearby_units(VISION_RADIUS_SQ):
        if c.get_team(uid) == my_team:
            continue
        if c.get_entity_type(uid) != EntityType.BUILDER_BOT:
            continue
        d = me.distance_squared(c.get_position(uid))
        if d < best_d:
            best_d = d
            best_id = uid
    return best_id


def _try_enter_follow(self: Healer, c: Controller) -> bool:
    """In PATROL, acquire a tracked enemy builder if one is in vision."""
    from builders.healer import HealState

    if self.follow_enemy_id is not None:
        return False
    eid = _pick_closest_enemy_builder(c)
    if eid is None:
        return False
    self.follow_enemy_id = eid
    self.state = HealState.FOLLOW
    return True


def _follow(self: Healer, c: Controller) -> None:
    from builders.healer import HealState

    enemy_id = self.follow_enemy_id
    if enemy_id is None:
        self.state = HealState.PATROL
        return

    enemy_pos = find_enemy_pos(c, enemy_id)
    if enemy_pos is None:
        c.self_destruct()
        return

    if c.get_move_cooldown() > 0:
        return

    me = c.get_position()
    # Close to Chebyshev <= 2 so we can react fast but don't overlap the enemy.
    if me.distance_squared(enemy_pos) <= 2:
        return
    step_toward(c, me, enemy_pos)
