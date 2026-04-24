from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller, EntityType, Position

from utils.defense.combat import step_toward

if TYPE_CHECKING:
    from builders.harvester import Harvester


_HEALABLE_TYPES = frozenset({
    EntityType.CONVEYOR,
    EntityType.BRIDGE,
    EntityType.CORE,
    EntityType.HARVESTER,
    EntityType.SPLITTER,
    EntityType.FOUNDRY,
})


def _find_damaged_in_vision(c: Controller) -> Position | None:
    """Return the position of the most-damaged allied healable building in vision."""
    my_team = c.get_team()
    best_pos: Position | None = None
    best_ratio = float("inf")
    for bid in c.get_nearby_buildings():
        if c.get_team(bid) != my_team:
            continue
        if c.get_entity_type(bid) not in _HEALABLE_TYPES:
            continue
        max_hp = c.get_max_hp(bid)
        hp = c.get_hp(bid)
        if hp >= max_hp:
            continue
        ratio = hp / max_hp
        if ratio < best_ratio:
            best_ratio = ratio
            best_pos = c.get_position(bid)
    return best_pos


def _try_enter_heal(self: Harvester, c: Controller) -> bool:
    from builders.harvester import HarvestState

    target = _find_damaged_in_vision(c)
    if target is None:
        return False
    self.heal_prev_state = self.state
    self.heal_interrupt_target = target
    self.state = HarvestState.HEAL
    return True


def _heal(self: Harvester, c: Controller) -> None:
    from builders.harvester import HarvestState

    # Validate current target — drop it if fully healed, gone, or no longer ours.
    if self.heal_interrupt_target is not None and c.is_in_vision(self.heal_interrupt_target):
        bid = c.get_tile_building_id(self.heal_interrupt_target)
        if (
            bid is None
            or c.get_team(bid) != c.get_team()
            or c.get_hp(bid) >= c.get_max_hp(bid)
        ):
            self.heal_interrupt_target = None

    # Find a new target if we need one.
    if self.heal_interrupt_target is None:
        self.heal_interrupt_target = _find_damaged_in_vision(c)

    # Nothing left to heal — return to previous state.
    if self.heal_interrupt_target is None:
        self.state = self.heal_prev_state if self.heal_prev_state is not None else HarvestState.SEEK
        self.heal_prev_state = None
        return

    target = self.heal_interrupt_target
    me = self.current_pos

    # Heal if within action radius and cooldown allows.
    if c.get_action_cooldown() == 0 and c.can_heal(target):
        c.heal(target)

    # Move toward target if not already adjacent.
    if c.get_move_cooldown() == 0 and me.distance_squared(target) > 2:
        step_toward(c, me, target)
