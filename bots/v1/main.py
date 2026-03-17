""" 
V1 Bot:
- Core: Spawn 8 bots (on random adjacent tiles?)
- Builder bot: Designate half to exploring and building turrets at enemy core
               Designate half to harvest ores and build conveyer belt back to own core
"""

import random

from cambc import Controller, Direction, EntityType, Environment, Position

# Non-centre directions
DIRECTIONS = [d for d in Direction if d != Direction.CENTRE]

class Player:
    def __init__(self):
        self.builders_spawned = 0

    """
    Units are entities which run an independent instance of run(), this includes: 
    - Core
    - Builder bots
    - Turrets (Gunner, Sentinel, Breach, Launcher)
    """
    def unit_core():
        if self.builders_spawned < 3:
            # if we haven't spawned 3 builder bots yet, try to spawn one on a random tile
            spawn_pos = ct.get_position().add(random.choice(DIRECTIONS))
            if ct.can_spawn(spawn_pos):
                ct.spawn_builder(spawn_pos)
                self.builders_spawned += 1

    def unit_builder_bot():
        # if we are adjacent to an ore tile, build a harvester on it
        for d in Direction:
            check_pos = ct.get_position().add(d)
            if ct.can_build_harvester(check_pos):
                ct.build_harvester(check_pos)
                break
        
        # move in a random direction
        move_dir = random.choice(DIRECTIONS)
        move_pos = ct.get_position().add(move_dir)
        # we need to place a conveyor or road to stand on, before we can move onto a tile
        if ct.can_build_road(move_pos):
            ct.build_road(move_pos)
        if ct.can_move(move_dir):
            ct.move(move_dir)

        # place a marker on an adjacent tile with the current round number
        marker_pos = ct.get_position().add(random.choice(DIRECTIONS))
        if ct.can_place_marker(marker_pos):
            ct.place_marker(marker_pos, ct.get_current_round())

    # Turret unit can be one of {Gunner, Sentinel, Breach, Launcher}
    def unit_turret(turret_etype: EntityType):
        match turret_etype:
            case EntityType.GUNNER:
                turret_gunner()
            case EntityType.SENTINEL:
                turret_sentinel()
            case EntityType.BREACH:
                turret_breach()
            case EntityType.LAUNCHER:
                turret_launcher()

    def turret_gunner():
        pass
    
    def turret_sentinel():
        pass
    
    def turret_breach():
        pass
    
    def turret_launcher():
        pass

    def run(self, ct: Controller) -> None:
        unit_etype = ct.get_entity_type()
        match unit_etype:
            case EntityType.CORE: 
                unit_core()
            case EntityType.BUILDER_BOT:
                unit_builder_bot()
            case _:
                unit_turret(unit_etype)