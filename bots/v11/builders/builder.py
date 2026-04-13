from enum import Enum
from cambc import Controller, EntityType
from builders.harvester import Harvester
from builders.attacker import Attacker
from utils.movement import (
    DIRECTIONS_4,
)


class BuilderRole(Enum):
    __slots__ = ()

    HARVESTER = "harvester"
    ATTACKER = "attacker"


class Builder:
    def __init__(self):
        self.role = None
        self.core_pos = None

    def run(self, c: Controller):
        if self.core_pos is None:
            for eid in c.get_nearby_buildings():
                if (
                    c.get_entity_type(eid) == EntityType.CORE
                    and c.get_team(eid) == c.get_team()
                ):
                    self.core_pos = c.get_position(eid)
                    break

        if self.core_pos is None:
            raise RuntimeError("Should've known where core was")

        if self.role is None:
            spawn_dir = self.core_pos.direction_to(c.get_position())
            if spawn_dir in DIRECTIONS_4:
                self.role = BuilderRole.HARVESTER
            else:
                self.role = BuilderRole.ATTACKER

        match self.role:
            case BuilderRole.HARVESTER:
                self.role = Harvester(self.core_pos)
            case BuilderRole.ATTACKER:
                self.role = Attacker(self.core_pos)

        # Builder bots can reassign their roles
        # e.g. Harvester.run() may return Attacker(self.core_pos)
        new_role = self.role.run(c)
        if new_role is not None:
            self.role = new_role
