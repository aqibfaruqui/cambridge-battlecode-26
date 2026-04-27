from __future__ import annotations
from typing import TYPE_CHECKING

from cambc import Controller

from utils.assassin_states import AssassinState

if TYPE_CHECKING:
    from builders.assassin import Assassin


# Stop chasing a candidate once we're this close (squared Chebyshev-ish);
# at this range vision will have either confirmed the core or eliminated
# enough symmetries to derive it.
_CANDIDATE_REACHED_DSQ = 20


def find_symmetry(self: Assassin, c: Controller) -> None:
    """Walk toward symmetry-candidate enemy-core positions until enemy_core_pos is known."""
    if self.enemy_core_pos is not None:
        self._state = AssassinState.FIND_ORE
        return

    candidate = self.enemy_core_candidates[self._candidate_idx]
    if self.current_pos.distance_squared(candidate) <= _CANDIDATE_REACHED_DSQ:
        self._candidate_idx = (self._candidate_idx + 1) % len(self.enemy_core_candidates)
        candidate = self.enemy_core_candidates[self._candidate_idx]

    self.target_pos = candidate
    self.navigate(c, candidate, lay_road=True)
