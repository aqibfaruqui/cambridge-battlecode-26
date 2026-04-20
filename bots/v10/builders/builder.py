from enum import IntEnum
from cambc import Controller, EntityType, Position
from builders.harvester_revamped import Harvester
from builders.attacker import Attacker
from builders.attacker_revamped import AttackerRevamped
from builders.healer import Healer


class BuilderType(IntEnum):
    EXTRA_ROLE_0 = 0     # (-1, -1)
    HARVESTER = 1        # ( 0, -1)
    EXTRA_ROLE_2 = 2     # ( 1, -1)
    ATTACKER = 3         # (-1,  0)
    ATTACKER_REVAMPED = 4     # ( 0,  0)
    HEALER = 5           # ( 1,  0)
    EXTRA_ROLE_6 = 6     # (-1,  1)
    EXTRA_ROLE_7 = 7     # ( 0,  1)
    EXTRA_ROLE_8 = 8     # ( 1,  1)

    @property
    def offset(self) -> tuple[int, int]:
        """dx, dy from core position. Derived from value assuming 3x3 grid."""
        dx = (self.value % 3) - 1  # -1, 0, 1
        dy = (self.value // 3) - 1  # -1, 0, 1
        return dx, dy

    def position_from_core(self, core_pos: Position) -> Position:
        dx, dy = self.offset
        return Position(core_pos.x + dx, core_pos.y + dy)

    @classmethod
    def from_offset(cls, dx: int, dy: int) -> "BuilderType":
        val = (dy + 1) * 3 + (dx + 1)
        return cls(val)


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

        if self.core_pos is None:
            raise ValueError("Expected core pos to be non-null")

        if self.role is None:
            my_pos = c.get_position()
            dx = my_pos.x - self.core_pos.x
            dy = my_pos.y - self.core_pos.y
            builder_type = BuilderType.from_offset(dx, dy)

            match builder_type:
                case BuilderType.HARVESTER:
                    self.role = Harvester(self.core_pos)
                case BuilderType.ATTACKER:
                    self.role = Attacker(self.core_pos)
                case BuilderType.HEALER:
                    self.role = Healer(self.core_pos)
                case BuilderType.ATTACKER_REVAMPED:
                    self.role = AttackerRevamped(self.core_pos)
                case _:
                    self.role = Attacker(self.core_pos)

        # Builder bots can reassign their roles
        # e.g. Harvester.run() may return Attacker(self.core_pos)
        new_role = self.role.run(c)
        if new_role is not None:
            self.role = new_role
