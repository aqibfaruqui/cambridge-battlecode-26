from enum import Enum
from cambc import Controller, EntityType, Position
from utils.movement import (
    DIRECTIONS_8,
    get_direction_8,
)


class AttackState(Enum):
    __slots__ = ()

    NAVIGATE = "navigate"
    PLACE_GUNNER = "place_gunner"
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

    def _search(self, c: Controller, target: Position):
        """Helper: Attempts to move bot towards target"""
        if c.get_move_cooldown() > 0:
            return

        pos = c.get_position()
        direction = get_direction_8(pos, target)
        for _ in range(8):
            next_pos = pos.add(direction)
            if not c.is_tile_passable(next_pos) and c.get_action_cooldown() == 0:
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
            if c.can_move(direction):
                c.move(direction)
                return

            direction = direction.rotate_right()

    def _navigate(self, c: Controller):
        """Navigate towards {self.attack_target} next to enemy core"""
        if self.enemy_pos is not None:
            if self.current_pos.distance_squared(self.attack_target) <= 4:
                self.attack_state = AttackState.PLACE_GUNNER
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

    def _place_gunner(self, c: Controller):
        """Place gunner next to enemy core"""
        if c.get_action_cooldown() == 0:
            for d in DIRECTIONS_8:
                adj = self.current_pos.add(d)
                bid = c.get_tile_building_id(adj)
                if bid is not None and c.get_team(bid) == c.get_team():
                    if c.get_entity_type(bid) in (EntityType.ROAD, EntityType.CONVEYOR):
                        c.destroy(adj)

                facing = adj.direction_to(self.enemy_pos)
                if c.can_build_gunner(adj, facing):
                    c.build_gunner(adj, facing)
                    self.gunners_placed += 1
                    if self.gunners_placed >= 2:
                        self.attack_state = AttackState.DONE
                    return

        self._search(c, self.attack_target)

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
                    break

        self.current_pos = c.get_position()

        match self.state:
            case AttackState.NAVIGATE:
                self._navigate(c)
            case AttackState.PLACE_GUNNER:
                self._place_gunner(c)
            case AttackState.DONE:
                self._done(c)
