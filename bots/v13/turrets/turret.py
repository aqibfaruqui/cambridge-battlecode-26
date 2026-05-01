from cambc import Controller, EntityType
from turrets.gunner import Gunner
from turrets.launcher import Launcher
from turrets.sentinel import Sentinel

class Turret:
    def __init__(self, turret_etype: EntityType):
        self.etype = turret_etype
        self.role: Gunner | Launcher | Sentinel | None = None
        self.core_pos = None

    def run(self, c: Controller):
        if self.core_pos is None:
            for eid in c.get_nearby_buildings():
                if (
                    c.get_entity_type(eid) == EntityType.CORE
                    and c.get_team(eid) == c.get_team()
                ):
                    self.core_pos = c.get_position(eid)


        if self.role is None:
            match self.etype:
                case EntityType.GUNNER:
                    self.role = Gunner()
                case EntityType.SENTINEL:
                    self.role = Sentinel()
                case EntityType.BREACH:
                    # self.role = Breach()
                    pass
                case EntityType.LAUNCHER:
                    self.role = Launcher(self.core_pos)

        if self.role is not None:
            self.role.run(c)
