from itertools import product

from cambc import Controller, Direction, EntityType, Position

from utils.assassin_states import AssassinState
from utils.assassin_states.attack import attack
from utils.assassin_states.find_ore import find_ore
from utils.assassin_states.find_symmetry import find_symmetry
from utils.assassin_states.patrol import patrol
from utils.comms.broadcaster import Broadcaster
from utils.comms.for_builder_bot import BuilderBotMessages
from utils.map.raw_map_representation import EnvironmentMap, Symmetry
from utils.pathfinding.d_star import DStarLite, _SEEK_BLOCK_MASK


class Assassin:
    """Builds a single harvester→conveyor→gunner pipeline aimed at the enemy core.

    Lifecycle: FIND_SYMMETRY → FIND_ORE → ATTACK → PATROL.
    """

    def __init__(self, c: Controller, core_pos: Position):
        self.core_pos = core_pos
        self.current_pos: Position = core_pos

        W, H = c.get_map_width(), c.get_map_height()
        cx, cy = core_pos.x, core_pos.y
        # Three reflections of own core — cycled through during exploration
        # until env-map symmetry resolves or we directly sight the enemy core.
        self.enemy_core_candidates: list[Position] = [
            Position(W - 1 - cx, H - 1 - cy),  # rotational
            Position(W - 1 - cx, cy),          # horizontal
            Position(cx, H - 1 - cy),          # vertical
        ]
        self._candidate_idx: int = 0
        self.enemy_core_pos: Position | None = None

        # Pipeline targets, picked in FIND_ORE.
        self.target_ore: Position | None = None
        self.target_stand_pos: Position | None = None      # cardinal of ore where bot stands
        self.target_gunner_pos: Position | None = None     # cardinal of enemy core where gunner ends up
        self.ore_blacklist: set[tuple[int, int]] = set()

        # ATTACK sub-phase markers (named to mirror harvester return_to_core
        # since the pipeline-laying mechanics are deliberately analogous).
        self.harvester_built: bool = False
        self.gunner_built: bool = False
        self.just_placed: bool = False
        self.bridge_jump_target: Position | None = None
        self.bridge_target_planner: DStarLite | None = None
        self.return_next_dir: Direction | None = None
        self.post_bridge_conveyor: bool = False
        self.bridge_fail_counts: dict[tuple[int, int, int, int], int] = {}

        # Harvester-placement sub-state (decide → step_on → ring → step_off → build).
        self.harvest_phase: str = "decide"
        self.harvest_sides_pending: list[Direction] = []
        self.harvest_ring_turns: int = 0

        # Shared planner; rebuilt when goal or bridges flag changes.
        self._env_map: EnvironmentMap = EnvironmentMap(W, H)
        self._planner: DStarLite | None = None
        self._planner_goal: tuple[int, int] | None = None
        self._planner_use_bridges: bool = False

        self._state: AssassinState = AssassinState.FIND_SYMMETRY
        self.target_pos: Position | None = None  # debug indicator

        self._broadcaster = Broadcaster()
        self._symmetry_broadcasted = False
        self._enemy_core_broadcasted = False

    # ---------- helpers shared across states ----------

    def _refresh_enemy_core(self, c: Controller) -> None:
        """Lock in enemy_core_pos from direct sight or resolved symmetry."""
        my_team = c.get_team()
        for eid in c.get_nearby_buildings():
            if c.get_entity_type(eid) == EntityType.CORE and c.get_team(eid) != my_team:
                self.enemy_core_pos = c.get_position(eid)
                return
        if self.enemy_core_pos is None:
            inferred = self._env_map.enemy_core_centre(self.core_pos)
            if inferred is not None:
                self.enemy_core_pos = inferred

    def _dynamic_blockers(self, c: Controller) -> list[tuple[int, int]]:
        """Other bots, harvesters, and the 3x3 ring around enemy launchers."""
        my_id = c.get_id()
        my_team = c.get_team()
        out: list[tuple[int, int]] = []
        for p in c.get_nearby_tiles():
            bot_id = c.get_tile_builder_bot_id(p)
            if bot_id is not None and bot_id != my_id:
                out.append((p.x, p.y))
                continue
            bid = c.get_tile_building_id(p)
            if bid is None:
                continue
            et = c.get_entity_type(bid)
            if et == EntityType.HARVESTER:
                out.append((p.x, p.y))
                continue
            if et == EntityType.LAUNCHER and c.get_team(bid) != my_team:
                out.extend((p.x + dx, p.y + dy) for dx, dy in product((-1, 0, 1), repeat=2))
        return out

    def navigate(self, c: Controller, target: Position, *, lay_road: bool = True) -> None:
        """D* step toward `target` over land (no bridges); pave roads as we go."""
        if c.get_move_cooldown() > 0:
            return
        goal = (target.x, target.y)
        if (
            self._planner is None
            or self._planner_goal != goal
            or self._planner_use_bridges
        ):
            self._planner = DStarLite(
                self._env_map, target.x, target.y,
                block_mask=_SEEK_BLOCK_MASK,
            )
            self._planner_goal = goal
            self._planner_use_bridges = False
        self._planner.set_position(self.current_pos.x, self.current_pos.y)
        self._planner.set_dynamic_blockers(self._dynamic_blockers(c))
        self._planner.notify_map_changes()
        d = self._planner.step()
        if d is None or d == Direction.CENTRE:
            return
        next_pos = self.current_pos.add(d)
        if lay_road and c.get_action_cooldown() == 0 and c.can_build_road(next_pos):
            c.build_road(next_pos)
        if c.can_move(d):
            c.move(d)

    # ---------- main loop ----------

    def run(self, c: Controller):
        self.current_pos = c.get_position()
        self._env_map.update(c)

        if not self._env_map.symmetry_resolved:
            raw = BuilderBotMessages.read_nearby_symmetry(c)
            if raw is not None:
                try:
                    self._env_map.force_symmetry(Symmetry(raw))
                except ValueError:
                    pass

        self._refresh_enemy_core(c)

        if self._env_map.symmetry is not None and not self._symmetry_broadcasted:
            self._broadcaster.add_broadcast(
                BuilderBotMessages.encode_symmetry(self._env_map.symmetry.value)
            )
            self._symmetry_broadcasted = True
        if self.enemy_core_pos is not None and not self._enemy_core_broadcasted:
            self._broadcaster.add_broadcast(
                BuilderBotMessages.encode_enemy_core_position(self.enemy_core_pos)
            )
            self._enemy_core_broadcasted = True

        match self._state:
            case AssassinState.FIND_SYMMETRY:
                find_symmetry(self, c)
            case AssassinState.FIND_ORE:
                find_ore(self, c)
            case AssassinState.ATTACK:
                attack(self, c)
            case AssassinState.PATROL:
                patrol(self, c)

        self._broadcaster.run(c)

        if self.target_pos is not None and self.target_pos != self.current_pos:
            c.draw_indicator_line(self.current_pos, self.target_pos, 200, 0, 100)
        c.draw_indicator_dot(self.current_pos, 200, 0, 100)

        print(
            f"[Assassin id={c.get_id()} pos=({self.current_pos.x},{self.current_pos.y})] "
            f"state={self._state.name} "
            f"enemy_core={self.enemy_core_pos} "
            f"target_ore={self.target_ore} "
            f"stand={self.target_stand_pos} "
            f"gunner={self.target_gunner_pos} "
            f"harvester_built={self.harvester_built} "
            f"gunner_built={self.gunner_built} "
            f"bridge_jump_target={self.bridge_jump_target}"
        )

