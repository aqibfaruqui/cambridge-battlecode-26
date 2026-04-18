from cambc import Controller, EntityType, Environment, Position

_SYM_ROT = "rot"   # 180° rotation:  mirror(x,y) = (W-1-x, H-1-y)
_SYM_HORZ = "horz" # horizontal flip: mirror(x,y) = (W-1-x, y)
_SYM_VERT = "vert" # vertical flip:   mirror(x,y) = (x, H-1-y)

UNKNOWN = 0
WALL = 1
TRAVERSABLE = 2
ORE_TI = 3
ORE_AX = 4
CORE_OWN = 5
CORE_ENEMY = 6


class MapMemory:
    """
    Map memory for bots, with symmetry inference
    Once we find a symmetry, we can project the known tiles onto the other side of the map.
    """

    def __init__(self):
        self._w: int = 0
        self._h: int = 0
        self._tiles: list[list[int]] | None = None
        
        # Predicted ores based on symmetry (not observed yet)
        self._pred_ti: set[tuple[int, int]] = set()
        self._pred_ax: set[tuple[int, int]] = set()
        self._known_ti: set[tuple[int, int]] = set()
        self._known_ax: set[tuple[int, int]] = set()

        # Core positions
        self._own_core: Position | None = None
        self._enemy_core: Position | None = None

        # Maybe we could keep track of covered tiles here?
        # Maybe we keep track of conveyors placed aswell? 

        # Symmetry candidates (rotation, horizontal flip, vertical flip)
        self._sym_candidates: set[str] = {_SYM_ROT, _SYM_HORZ, _SYM_VERT}
        self._sym_confirmed: str | None = None
        self._sym_projected: bool = False  # full back-fill done once on confirmation
        self.version: int = 0  # incremented when a blocking tile is newly found



    def update(self, c: Controller):
        """Call once per turn to integrate new vision data."""
        if self._tiles is None:
            self._w = c.get_map_width()
            self._h = c.get_map_height()
            self._tiles = [[UNKNOWN] * self._w for _ in range(self._h)]
            if self._own_core is not None:
                self._mark_core_footprint(self._own_core, CORE_OWN)

        newly_seen: list[Position] = []
        pred_ti = self._pred_ti
        pred_ax = self._pred_ax
        find_enemy_core = self._enemy_core is None
        my_team = c.get_team() if find_enemy_core else None

        for pos in c.get_nearby_tiles():
            px = pos.x
            py = pos.y

            # Spot enemy core while we still haven't found it.
            if find_enemy_core:
                bid = c.get_tile_building_id(pos)
                if bid is not None and c.get_entity_type(bid) == EntityType.CORE and c.get_team(bid) != my_team:
                    self._enemy_core = c.get_position(bid)
                    if self._tiles is not None:
                        self._mark_core_footprint(self._enemy_core, CORE_ENEMY)
                    find_enemy_core = False

            # Tile state never changes once it is classified.
            if self._tiles[py][px] != UNKNOWN:
                # Clean up any projected-ore entry we can now physically confirm.
                # Guard avoids tuple creation once both sets are empty (common case).
                if pred_ti or pred_ax:
                    pred_ti.discard((px, py))
                    pred_ax.discard((px, py))
                continue

            env = c.get_tile_env(pos)
            if env == Environment.WALL:
                state = WALL
            elif env == Environment.ORE_TITANIUM:
                state = ORE_TI
            elif env == Environment.ORE_AXIONITE:
                state = ORE_AX
            else:
                state = TRAVERSABLE

            self._tiles[py][px] = state
            self._update_ore_sets(px, py, state, observed=True)
            newly_seen.append(pos)

            # Only bump version for blocking tiles, TRAVERSABLE was already
            # treated as passable (optimistic), so discovering open ground
            # doesn't change any routing decisions.
            if state != TRAVERSABLE:
                self.version += 1

        if newly_seen:
            if self._sym_confirmed is None:
                self._refine_symmetry(newly_seen)
            if self._sym_confirmed:
                if not self._sym_projected:
                    # First time symmetry is confirmed, fill in all observed tiles.
                    self._project_all()
                    self._sym_projected = True
                else:
                    self._project_symmetry(newly_seen)

    def set_core(self, pos: Position):
        """Record our own core position. Call once during harvester init."""
        self._own_core = pos
        self._try_resolve_enemy_core()
        self._mark_core_footprint(self._own_core, CORE_OWN)

    def nearest_predicted_titanium(self, origin: Position) -> Position | None:
        """Nearest symmetry-predicted titanium ore (never directly observed)."""
        return self._nearest(origin, self._pred_ti)

    def nearest_predicted_axionite(self, origin: Position) -> Position | None:
        """Nearest symmetry-predicted axionite ore (never directly observed)."""
        return self._nearest(origin, self._pred_ax)

    def nearest_known_titanium(
        self,
        origin: Position,
        blocked: set[tuple[int, int]] | None = None,
    ) -> Position | None:
        return self._nearest(origin, self._known_ti, blocked)

    def nearest_known_axionite(
        self,
        origin: Position,
        blocked: set[tuple[int, int]] | None = None,
    ) -> Position | None:
        return self._nearest(origin, self._known_ax, blocked)

    def nearest_known_ore(
        self,
        origin: Position,
        blocked: set[tuple[int, int]] | None = None,
    ) -> Position | None:
        titanium = self._nearest(origin, self._known_ti, blocked)
        axionite = self._nearest(origin, self._known_ax, blocked)
        if titanium is None:
            return axionite
        if axionite is None:
            return titanium
        if origin.distance_squared(titanium) <= origin.distance_squared(axionite):
            return titanium
        return axionite

    def symmetry(self) -> str | None:
        return self._sym_confirmed

    # Helpers

    def _try_resolve_enemy_core(self):
        """Compute enemy core once we have both our core position and confirmed symmetry."""
        if self._enemy_core is not None:
            return
        if self._own_core is None or self._sym_confirmed is None:
            return
        mx, my = self._mirror(self._own_core.x, self._own_core.y, self._sym_confirmed)
        self._enemy_core = Position(mx, my)
        if self._tiles is not None:
            self._mark_core_footprint(self._enemy_core, CORE_ENEMY)

    def _mark_core_footprint(self, centre: Position, state: int):
        """Mark the 3x3 footprint of a core with the given tile state."""
        tiles = self._tiles
        if tiles is None:
            return
        cx, cy = centre.x, centre.y
        for dy in range(-1, 2):
            for dx in range(-1, 2):
                x, y = cx + dx, cy + dy
                if 0 <= x < self._w and 0 <= y < self._h:
                    if tiles[y][x] == UNKNOWN:
                        tiles[y][x] = state

    def _update_ore_sets(self, x: int, y: int, new: int, observed: bool = True):
        key = (x, y)
        self._pred_ti.discard(key)
        self._pred_ax.discard(key)
        self._known_ti.discard(key)
        self._known_ax.discard(key)

        if observed:
            if new == ORE_TI:
                self._known_ti.add(key)
            elif new == ORE_AX:
                self._known_ax.add(key)
        elif new == ORE_TI:
            self._pred_ti.add(key)
        elif new == ORE_AX:
            self._pred_ax.add(key)

    def _mirror(self, x: int, y: int, sym: str) -> tuple[int, int]:
        # Mirror the tile coordinates based on the symmetry candidate
        if sym == _SYM_ROT:
            return (self._w - 1 - x, self._h - 1 - y)
        if sym == _SYM_HORZ:
            return (self._w - 1 - x, y)
        return (x, self._h - 1 - y)  # _SYM_VERT

    def _refine_symmetry(self, new_tiles: list[Position]):
        """Eliminate symmetry candidates that contradict observations"""
        assert self._tiles is not None
        for pos in new_tiles:
            state = self._tiles[pos.y][pos.x]
            for sym in list(self._sym_candidates):
                # Get the mirror tile coordinates
                mx, my = self._mirror(pos.x, pos.y, sym)
                if not (0 <= mx < self._w and 0 <= my < self._h):
                    continue

                # Check if the mirror tile is known
                mirror_state = self._tiles[my][mx]
                if mirror_state == UNKNOWN:
                    continue

                # If the tile and its mirror are known but have different states, eliminate the symmetry candidate
                if state != mirror_state:
                    self._sym_candidates.discard(sym)

        # If we have only one symmetry candidate left, we can confirm it
        if self._sym_confirmed is None and len(self._sym_candidates) == 1:
            self._sym_confirmed = next(iter(self._sym_candidates))
            self._try_resolve_enemy_core()

    def _project_all(self):
        """One-time back-fill: project every already-classified tile to its mirror."""
        tiles = self._tiles
        sym = self._sym_confirmed
        assert tiles is not None
        assert sym is not None
        for y in range(self._h):
            for x in range(self._w):
                state = tiles[y][x]
                if state == UNKNOWN:
                    continue
                mx, my = self._mirror(x, y, sym)
                if not (0 <= mx < self._w and 0 <= my < self._h):
                    continue
                if tiles[my][mx] != UNKNOWN:
                    continue
                tiles[my][mx] = state
                self._update_ore_sets(mx, my, state, observed=False)
                if state != TRAVERSABLE:
                    self.version += 1

    def _project_symmetry(self, new_tiles: list[Position]):
        """If we know symmetry project other tiles onto the other side of the map"""
        tiles = self._tiles
        sym = self._sym_confirmed
        if sym is None or tiles is None:
            return

        for pos in new_tiles:
            state = tiles[pos.y][pos.x]
            mx, my = self._mirror(pos.x, pos.y, sym)
            if not (0 <= mx < self._w and 0 <= my < self._h):
                continue
            if tiles[my][mx] != UNKNOWN:
                continue
            tiles[my][mx] = state
            self._update_ore_sets(mx, my, state, observed=False)
            # Projected blocking tiles change the BFS topology, invalidate cache.
            if state != TRAVERSABLE:
                self.version += 1

    def _nearest(
        self,
        origin: Position,
        ore_set: set[tuple[int, int]],
        blocked: set[tuple[int, int]] | None = None,
    ) -> Position | None:
        """Helper function to find the nearest ore tile"""
        best_pos: Position | None = None
        best_dist = float("inf")
        ox, oy = origin.x, origin.y
        for x, y in ore_set:
            if blocked is not None and (x, y) in blocked:
                continue
            dist = (x - ox) * (x - ox) + (y - oy) * (y - oy)
            if dist < best_dist:
                best_dist = dist
                best_pos = Position(x, y)
        return best_pos


    # def debug_render(self, turn: int):
    #     """Print an ASCII snapshot of the map to stderr."""
    #     if self._tiles is None:
    #         print(f"[turn {turn}] MapMemory: not yet initialised", file=sys.stderr)
    #         return

    #     _CHARS = {UNKNOWN: "?", WALL: "#", TRAVERSABLE: ".", ORE_TI: "T", ORE_AX: "A", CORE_OWN: "C", CORE_ENEMY: "E"}
    #     known = sum(1 for row in self._tiles for t in row if t != UNKNOWN)
    #     total = self._w * self._h
    #     pct = 100 * known // total

    #     own = self._own_core
    #     enemy = self._enemy_core
    #     print(
    #         f"\n=== MapMemory turn {turn} | {self._w}x{self._h} | {pct}% explored"
    #         f" | sym={self._sym_confirmed or 'TBD'}"
    #         f" | own_core={own} enemy_core={enemy}"
    #         f" | pred_ti={len(self._pred_ti)} pred_ax={len(self._pred_ax)} ===",
    #         file=sys.stderr,
    #     )
    #     for row in reversed(self._tiles):  # y=0 at bottom, print top-down
    #         print("".join(_CHARS[t] for t in row), file=sys.stderr)
    #     print("=== end ===\n", file=sys.stderr)
