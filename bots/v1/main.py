""" 
V1 Bot:
- Core: Spawn 8 bots on random adjacent tiles
- Builder Bot: Designate half to harvest ores and build conveyer belt back to our core
               Designate half to exploring and building turrets at enemy core

Test code runs with: cambc run starter v1
"""

import sys      # For print(f'...', file=sys.stderr)
import random

from cambc import Controller, Direction, EntityType, Environment, Position

# Non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]
BUILDER_COUNT = 8

class Player:
    def __init__(self):
        self.builders_spawned = 0
        self.harvest_builder_ids = set()
        self.attack_builder_ids  = set()

    """
    Units are entities which run an independent instance of run(), this includes: 
    - Core
    - Builder bots
    - Turrets (Gunner, Sentinel, Breach, Launcher)
    """
    def unit_core(self, c: Controller):
        if self.builders_spawned < BUILDER_COUNT:
            spawn_pos = c.get_position().add(random.choice(DIRECTIONS))
            if c.can_spawn(spawn_pos):
                c.spawn_builder(spawn_pos)      # Try to spawn builder on random adjacent tile
                self.builders_spawned += 1

    def unit_builder_bot(self, c: Controller):
        # TODO: Fix hacky way of assigning half of builder bots to each role
        #
        # Implemented like this because:
        # > id is not incremented consistently so cannot use odd/even
        # > c.spawn_builder() does not return id to assign role on spawning (developers said they will add this :D)
        id = c.get_id()
        if id not in self.harvest_builder_ids and len(self.harvest_builder_ids) < BUILDER_COUNT / 2:
            self.harvest_builder_ids.add(id)
        elif id not in self.attack_builder_ids and len(self.attack_builder_ids) < BUILDER_COUNT / 2:
            self.attack_builder_ids.add(id)
            
        if id in self.harvest_builder_ids:
            self.harvest_builder(c)
        elif id in self.attack_builder_ids:
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
        pass
    
    def turret_sentinel(self, c: Controller):
        pass
    
    def turret_breach(self, c: Controller):
        pass
    
    def turret_launcher(self, c: Controller):
        pass

    # TODO: Implement conveyor path from harvesters back to core
    #       (this is currently just the starter bot code)
    def harvest_builder(self, c: Controller):
        # If we are adjacent to an ore tile, build a harvester on it
        for d in Direction:
            check_pos = c.get_position().add(d)
            if c.can_build_harvester(check_pos):
                c.build_harvester(check_pos)
                return
        
        # Move in a random direction
        move_dir = random.choice(DIRECTIONS)
        move_pos = c.get_position().add(move_dir)
        
        # We need to place a conveyor or road to stand on, before we can move onto a tile
        if c.can_build_road(move_pos):
            c.build_road(move_pos)
        if c.can_move(move_dir):
            c.move(move_dir)

        # Place a marker on an adjacent tile with the current round number
        marker_pos = c.get_position().add(random.choice(DIRECTIONS))
        if c.can_place_marker(marker_pos):
            c.place_marker(marker_pos, c.get_current_round())

    # TODO: Implement enemy core finding and turret placing
    def attack_builder(self, c: Controller):
        pass

    def run(self, c: Controller) -> None:
        unit_etype = c.get_entity_type()
        match unit_etype:
            case EntityType.CORE: 
                self.unit_core(c)
            case EntityType.BUILDER_BOT:
                self.unit_builder_bot(c)
            case _:
                self.unit_turret(c, unit_etype)