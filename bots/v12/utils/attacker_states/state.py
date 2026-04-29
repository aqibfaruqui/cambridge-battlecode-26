from enum import Enum


class AttackState(Enum):
    SCAN = "scan"              # Probing for an enemy harvester→conveyor to hijack
    APPROACH = "approach"      # Walking onto a locked-in target conveyor
    REPLACE = "replace"        # On-tile: fire conveyor → step off → sentinel
    PROACTIVE = "proactive"    # If we are in scan or replace for too long 
