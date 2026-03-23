from enum import Enum
from cambc import Controller, EntityType, Position
from utils.movement import (
    bug_nav,
)


class AttackState(Enum):
    __slots__ = ()

    NAVIGATE = "navigate"
    PLACE_SELF_DESTRUCT = "place_self_destruct"
    DONE = "done"


class Attacker:
    def __init__(self, core_pos: Position):
        self.state = AttackState.NAVIGATE
        self.core_pos = core_pos
        self.enemy_pos = None
        self.current_pos = None
        self.attack_target = None
        self.gunners_placed = 0
        self.enemy_core_candidate_idx = 0
        self.enemy_core_candidates = []
        self._bug_follow_state: dict | None = None

    def _search(self, c: Controller, target: Position):
        """Helper: navigate towards target with bug nav and pave if needed."""
        if c.get_move_cooldown() > 0:
            return

        pos = c.get_position()
        direction, self._bug_follow_state = bug_nav(
            c, pos, target, self._bug_follow_state
        )
        if direction is None:
            return

        next_pos = pos.add(direction)
        if c.can_move(direction):
            c.move(direction)
            return

        if c.get_action_cooldown() == 0 and c.can_build_road(next_pos):
            c.build_road(next_pos)

    def _navigate(self, c: Controller):
        """Navigate towards {self.attack_target} next to enemy core"""
        if self.enemy_pos is not None:
            if self.current_pos.distance_squared(self.attack_target) <= 4:
                self.state = AttackState.PLACE_SELF_DESTRUCT
            else:
                self._search(c, self.attack_target)
        else:
            # Cycle through candidates
            if (
                self.current_pos.distance_squared(
                    self.enemy_core_candidates[self.enemy_core_candidate_idx]
                )
                <= 20
            ):
                self.enemy_core_candidate_idx = (self.enemy_core_candidate_idx + 1) % 3
            self._search(c, self.enemy_core_candidates[self.enemy_core_candidate_idx])

    def _place_self_destruct(self, c: Controller):
        """Look for enemy logistics near the enemy core and self destruct"""
        target_pos = None
        best_dist = float("inf")

        for eid in c.get_nearby_entities():
            if c.get_team(eid) == c.get_team():
                continue
            if c.get_entity_type(eid) not in (
                EntityType.CONVEYOR,
                EntityType.BRIDGE
            ):
                continue

            pos = c.get_position(eid)
            dist = pos.distance_squared(self.enemy_pos)
            if dist < best_dist:
                best_dist = dist
                target_pos = pos

        if target_pos is not None:
            if self.current_pos == target_pos and c.can_fire(target_pos):
                c.fire(target_pos)
                return
            
            self._search(c, target_pos)
            return

        self._search(c, self.enemy_pos)

    def _done(self, c: Controller):
        """TODO: Heal gunners & Supply ammo"""
        pass

    def run(self, c: Controller):
        # Calculate enemy core candidates once
        if len(self.enemy_core_candidates) == 0:
            cx, cy = self.core_pos.x, self.core_pos.y
            W, H = c.get_map_width(), c.get_map_height()
            self.enemy_core_candidates = [
                Position(W - 1 - cx, H - 1 - cy),  # Rotational (180°)
                Position(W - 1 - cx, cy),  # Horizontal reflection
                Position(cx, H - 1 - cy),  # Vertical reflection
            ]
            self.enemy_core_candidate_idx = c.get_current_round() % 3
            return

        # TODO: Use markers to broadcast confirmed enemy position to other builders

        # Check we are targetting correct enemy core
        if self.enemy_pos is None:
            for eid in c.get_nearby_buildings():
                if (
                    c.get_entity_type(eid) == EntityType.CORE
                    and c.get_team(eid) != c.get_team()
                ):
                    self.enemy_pos = c.get_position(eid)
                    # Navigates to two tiles outside the enemy core
                    approach = self.core_pos.direction_to(self.enemy_pos)
                    adx, ady = approach.delta()
                    self.attack_target = Position(
                        self.enemy_pos.x - adx * 2,
                        self.enemy_pos.y - ady * 2,
                    )
                    self._bug_follow_state = None
                    break

        self.current_pos = c.get_position()

        match self.state:
            case AttackState.NAVIGATE:
                self._navigate(c)
            case AttackState.PLACE_SELF_DESTRUCT:
                self._place_self_destruct(c)
            case AttackState.DONE:
                self._done(c)
