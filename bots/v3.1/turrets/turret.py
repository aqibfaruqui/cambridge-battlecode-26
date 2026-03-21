from cambc import Controller, EntityType
from turrets.gunner import Gunner


class Turret:
    def __init__(self, turret_etype: EntityType):
        self.role = turret_etype

    def run(self, c: Controller):
        match self.role:
            case EntityType.GUNNER:
                self.role = Gunner()
            case EntityType.SENTINEL:
                # self.role = Sentinel()
                pass
            case EntityType.BREACH:
                # self.role = Breach()
                pass
            case EntityType.LAUNCHER:
                # self.role = Launcher()
                pass

        self.role.run(c)
