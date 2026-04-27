from enum import Enum 

class AssassinState(Enum):
    FIND_SYMMETRY = "find_symmetry"
    FIND_ORE = "find_ore"
    ATTACK = "attack"
    PATROL = "patrol"