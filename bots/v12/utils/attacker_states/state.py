from enum import Enum


class AttackState(Enum):
    SCAN = "scan"              # Probing for an enemy harvester→conveyor to hijack
    APPROACH = "approach"      # Walking onto a locked-in target conveyor
    REPLACE = "replace"        # On-tile: fire conveyor → step off → sentinel
    PROACTIVE = "proactive"    # Enemy-core-adjacent exploration after no replacement
    BLOCK_HARVESTER = "block_harvester"  # Build a gunner cardinally adjacent to enemy harvester
