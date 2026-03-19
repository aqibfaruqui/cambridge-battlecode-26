""" 
V1 Bot:
- Core: Spawn 8 bots on random adjacent tiles
- Builder Bot: Designate half to harvest ores and build conveyer belt back to our core
               Designate half to exploring and building turrets at enemy core

Test code runs with: cambc run starter v1
"""

import sys      # For print(f'...', file=sys.stderr)
import random
from enum import Enum, auto

from cambc import Controller, Direction, EntityType, Environment, Position, Team
from movement import get_direction_4, get_direction_8, random_direction_4, random_direction_8, reached_core

BUILDER_COUNT = 8

class BuilderRole(Enum):
    HARVESTER = auto()
    ATTACKER = auto()

class HarvestState(Enum):
    NOT_PLACED = auto()
    JUST_PLACED = auto()
    RETURNING_TO_CORE = auto()

class AttackPhase(Enum):
    NAVIGATE = auto()
    PLACE_GUNNER = auto()
    DONE = auto()

"""
Units are entities which run an independent instance of Player.run(), this includes: 
- Core
- Builder bots
- Turrets (Gunner, Sentinel, Breach, Launcher)
"""
class Player:
    def __init__(self):
        # Core Attributes
        self.builders_spawned = 0

        # General Builder Bot Attributes
        self.role = None
        self.core_pos = None
        
        # Harvest Builder Bot Attributes
        self.harvest_state = HarvestState.NOT_PLACED
        
        # Attack Builder Bot Attributes
        self.enemy_core_candidates = []
        self.enemy_core_candidate_idx = 0
        self.enemy_pos = None
        self.attack_target = None
        self.gunners_placed = 0
        self.attack_state = AttackPhase.NAVIGATE
    
        # Turret Attributes
        # ...
    
    def unit_core(self, c: Controller):
        if self.core_pos is None:
            self.core_pos = c.get_position()

        if self.builders_spawned < BUILDER_COUNT:
            spawn_pos = c.get_position().add(random_direction_8())
            if c.can_spawn(spawn_pos):
                c.spawn_builder(spawn_pos)      # Try to spawn builder on random adjacent tile
                self.builders_spawned += 1

    def unit_builder_bot(self, c: Controller):
        if self.core_pos is None:
            for eid in c.get_nearby_buildings():
                if (c.get_entity_type(eid) == EntityType.CORE and c.get_team(eid) == c.get_team()):
                    self.core_pos = c.get_position(eid)    

        if self.role is None:
            self.role = random.choice(list(BuilderRole))

        match self.role:
            case BuilderRole.HARVESTER:
                self.harvest_builder(c)
            case BuilderRole.ATTACKER:
                self.attack_builder(c)

    # Turret unit can be one of {Gunner, Sentinel, Breach, Launcher}
    def unit_turret(self, c: Controller, turret_etype: EntityType):
        match turret_etype:
            case EntityType.GUNNER:
                self.turret_gunner()
            case EntityType.SENTINEL:
                self.turret_sentinel()
            case EntityType.BREACH:
                self.turret_breach()
            case EntityType.LAUNCHER:
                self.turret_launcher()

    def turret_gunner(self, c: Controller):
        target = c.get_gunner_target()
        if target is not None and c.can_fire(target):
            c.fire(target)
    
    def turret_sentinel(self, c: Controller):
        pass
    
    def turret_breach(self, c: Controller):
        pass
    
    def turret_launcher(self, c: Controller):
        pass

    def harvest_builder(self, c: Controller):
        id = c.get_id()
        current_pos = c.get_position()

        # If builder has just placed harvester, replace stood on road with conveyor
        if self.harvest_state == HarvestState.JUST_PLACED:
            move_dir = get_direction_4(current_pos, self.core_pos)

            if c.get_entity_type(c.get_tile_building_id(current_pos)) == EntityType.ROAD and c.can_destroy(current_pos):
                c.destroy(current_pos)

            if c.can_build_conveyor(current_pos, move_dir):
                c.build_conveyor(current_pos, move_dir)

            self.harvest_state = HarvestState.RETURNING_TO_CORE
            return

        # If builder has placed harvester, lay conveyor path back to core
        if self.harvest_state == HarvestState.RETURNING_TO_CORE:
            move_dir = get_direction_4(current_pos, self.core_pos)
            move_pos = current_pos.add(move_dir)

            entity_type = c.get_entity_type(c.get_tile_building_id(move_pos))
            if entity_type == EntityType.ROAD and c.can_destroy(move_pos):
                c.destroy(move_pos)

            next_move_dir = get_direction_4(move_pos, self.core_pos)    # Needed for conveyors to turn corners

            if c.can_build_conveyor(move_pos, next_move_dir):
                c.build_conveyor(move_pos, next_move_dir)
                
                if c.can_move(move_dir):
                    c.move(move_dir)

            if reached_core(c.get_position(), self.core_pos):
                self.harvest_state = HarvestState.NOT_PLACED

            return

        # If we are adjacent to an ore tile in first half of the game, build a harvester on it
        if c.get_current_round() < 1000:
            for d in Direction:
                ore_pos = current_pos.add(d)
                if c.can_build_harvester(ore_pos):
                    c.build_harvester(ore_pos)
                    self.harvest_state = HarvestState.JUST_PLACED
                    return
                
        # Else keep exploring, place a road to stand on before we move onto a tile
        move_dir = random_direction_8()
        move_pos = c.get_position().add(move_dir)
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(move_dir):
            c.move(move_dir)

    def attack_builder(self, c: Controller):
        # First time we see the enemy core, we need to calculate the candidates
        if self.core_pos is None:
            for eid in c.get_nearby_buildings():
                if (c.get_entity_type(eid) == EntityType.CORE and c.get_team(eid) == c.get_team()):
                    self.core_pos = c.get_position(eid)

        if self.enemy_core_candidates is None or self.enemy_core_candidate_idx == 0:
            cx, cy = self.core_pos.x, self.core_pos.y
            W, H = c.get_map_width(), c.get_map_height()
            self.enemy_core_candidates = [
                Position(W - 1 - cx, H - 1 - cy),    # Rotational (180°)
                Position(W - 1 - cx, cy),            # Horizontal reflection
                Position(cx, H - 1 - cy),            # Vertical reflection
            ]

            self.enemy_core_candidate_idx = c.get_current_round() % 3
            return

        # TODO: use markers to broadcast confirmed enemy position to other builders

        # Check we are targetting correct enemy core
        if self.enemy_pos is None:
            for eid in c.get_nearby_buildings():
                if (c.get_entity_type(eid) == EntityType.CORE and c.get_team(eid) != c.get_team()):
                    self.enemy_pos = c.get_position(eid)
                    # Navigates to two tiles outside the enemy core
                    approach = self.core_pos.direction_to(self.enemy_pos)
                    adx, ady = approach.delta()
                    self.attack_target = Position(
                        self.enemy_pos.x - adx * 2,
                        self.enemy_pos.y - ady * 2,
                    )
                    break

        # If we confirm enemy core, navigate to it
        if self.enemy_pos is not None:
            self._navigate(c, self.enemy_pos)
            return

        # Visit different candidates in order based on spawn turn
        pos = c.get_position()

        if self.attack_state == AttackPhase.NAVIGATE:
            if self.enemy_pos is not None:
                # TODO: change this to whatever turret you use
                if pos.distance_squared(self.attack_target) <= 4: 
                    self.attack_state = AttackPhase.PLACE_GUNNER
                else:
                    self._navigate(c, self.attack_target)
            else:
                # Cycle through candidates
                if pos.distance_squared(self.enemy_core_candidates[self.enemy_core_candidate_idx]) <= 20:
                    self.enemy_core_candidate_idx = (self.enemy_core_candidate_idx + 1) % 3
                self._navigate(c, self.enemy_core_candidates[self.enemy_core_candidate_idx])

        elif self.attack_state == AttackPhase.PLACE_GUNNER:
            if c.get_action_cooldown() == 0:
                for d in DIRECTIONS:
                    adj = pos.add(d)
                    # Clear allied roads to make room for gunner
                    bid = c.get_tile_building_id(adj)
                    if bid is not None and c.get_team(bid) == c.get_team():
                        if c.get_entity_type(bid) in (EntityType.ROAD, EntityType.CONVEYOR):
                            c.destroy(adj)
                    facing = adj.direction_to(self.enemy_pos)
                    if c.can_build_gunner(adj, facing):
                        c.build_gunner(adj, facing)
                        self.gunners_placed += 1
                        if self.gunners_placed >= 2:
                            self.attack_state = AttackPhase.DONE
                        return
            self._navigate(c, self.attack_target)

        elif self.attack_state == AttackPhase.DONE:
            pass  # TODO: heal gunners, supply ammo

    def _navigate(self, c: Controller, target: Position):
        if c.get_move_cooldown() > 0:
            return

        pos = c.get_position()
        direction = pos.direction_to(target)
        for _ in range(8):
            next_pos = pos.add(direction)
            if not c.is_tile_passable(next_pos) and c.get_action_cooldown() == 0:
                if c.can_build_road(next_pos):
                    c.build_road(next_pos)
            if c.can_move(direction):
                c.move(direction)
                return

            direction = direction.rotate_right()

    def run(self, c: Controller) -> None:
        unit_etype = c.get_entity_type()
        match unit_etype:
            case EntityType.CORE: 
                self.unit_core(c)
            case EntityType.BUILDER_BOT:
                self.unit_builder_bot(c)
            case _:
                self.unit_turret(c, unit_etype)