from cambc import Controller, Environment, Position

_SYM_ROT = "rot"   # 180° rotation:  mirror(x,y) = (W-1-x, H-1-y)
_SYM_HORZ = "horz" # horizontal flip: mirror(x,y) = (W-1-x, y)
_SYM_VERT = "vert" # vertical flip:   mirror(x,y) = (x, H-1-y)

UNKNOWN = 0
WALL = 1
TRAVERSABLE = 2
ORE_TI = 3
ORE_AX = 4


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

        # Maybe we could keep track of covered tiles here?
        # Maybe we keep track of conveyors placed aswell? 

        # Symmetry candidates (rotation, horizontal flip, vertical flip)
        self._sym_candidates: set[str] = {_SYM_ROT, _SYM_HORZ, _SYM_VERT}
        self._sym_confirmed: str | None = None
        self.version: int = 0  # incremented when a blocking tile is newly found



    def update(self, c: Controller):
        """Call once per turn to integrate new vision data."""
        if self._tiles is None:
            self._w = c.get_map_width()
            self._h = c.get_map_height()
            self._tiles = [[UNKNOWN] * self._w for _ in range(self._h)]

        newly_seen: list[Position] = []
        pred_ti = self._pred_ti
        pred_ax = self._pred_ax

        for pos in c.get_nearby_tiles():
            px = pos.x
            py = pos.y

            # Discard any predicted entry the moment we can actually see the
            # tile, even if it was already classified via symmetry projection.
            key = (px, py)
            if key in pred_ti:
                pred_ti.discard(key)
            elif key in pred_ax:
                pred_ax.discard(key)

            # Tile state never changes once it is classified
            if self._tiles[py][px] != UNKNOWN:
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
                self._project_symmetry(newly_seen)

    def nearest_predicted_titanium(self, origin: Position) -> Position | None:
        """Nearest symmetry-predicted titanium ore (never directly observed)."""
        return self._nearest(origin, self._pred_ti)

    def nearest_predicted_axionite(self, origin: Position) -> Position | None:
        """Nearest symmetry-predicted axionite ore (never directly observed)."""
        return self._nearest(origin, self._pred_ax)

    def symmetry(self) -> str | None:
        return self._sym_confirmed

    # Helpers

    def _update_ore_sets(self, x: int, y: int, new: int, observed: bool = True):
        # Update predicted ores based on the new tile state
        # Maybe we can delete this (not sure if optimal just a note)
        key = (x, y)
        if observed:
            self._pred_ti.discard(key)
            self._pred_ax.discard(key)
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

    def _project_symmetry(self, new_tiles: list[Position]):
        """If we know symmetry project other tiles onto the other side of the map"""
        if self._sym_confirmed is None:
            return

        for pos in new_tiles:
            state = self._tiles[pos.y][pos.x]
            mx, my = self._mirror(pos.x, pos.y, self._sym_confirmed)
            if not (0 <= mx < self._w and 0 <= my < self._h):
                continue
            if self._tiles[my][mx] != UNKNOWN:
                continue
            self._tiles[my][mx] = state
            self._update_ore_sets(mx, my, state, observed=False)
            # Projected blocking tiles change the BFS topology, invalidate cache.
            if state != TRAVERSABLE:
                self.version += 1

    def _nearest(
        self, origin: Position, ore_set: set[tuple[int, int]]
    ) -> Position | None:
        """Helper function to find the nearest ore tile"""
        best_pos: Position | None = None
        best_dist = float("inf")
        ox, oy = origin.x, origin.y
        for x, y in ore_set:
            dist = (x - ox) * (x - ox) + (y - oy) * (y - oy)
            if dist < best_dist:
                best_dist = dist
                best_pos = Position(x, y)
        return best_pos


