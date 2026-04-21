from cambc import Position, Controller, EntityType

from utils.comms.for_launcher import LauncherMessages, LauncherMessageType


# Launcher throw range (r² ≤ 26) and builder action radius (r² = 2).
_THROW_RANGE_SQ = 26
_ACTION_RADIUS_SQ = 2
# |dx|,|dy| bound s.t. dx²+dy² ≤ 26.
_THROW_SPAN = 5

# ONETIME_SEND_OURS encodes only the low 12 bits of the requester's bot id.
_BOT_ID_MASK = 0xFFF


class Launcher:
    def __init__(self, core_pos: Position | None):
        self.core_pos = core_pos
        self.idle_rounds = 0
        # Bots we've already thrown whose request marker we couldn't destroy
        # (marker out of our r²≤2 destroy range). Prevents re-throwing them
        # while the stale marker lingers in our vision.
        self._serviced_bot_ids: set[int] = set()

    def _read_launch_requests(
        self, c: Controller
    ) -> list[tuple[int, Position, Position]]:
        """Own-team ONETIME_SEND_OURS markers in vision → [(bot_id_low12, target, marker_pos)]."""
        my_team = c.get_team()
        requests: list[tuple[int, Position, Position]] = []
        for bld_id in c.get_nearby_buildings():
            if c.get_entity_type(bld_id) != EntityType.MARKER:
                continue
            if c.get_team(bld_id) != my_team:
                continue
            value = c.get_marker_value(bld_id)
            if LauncherMessages.get_message_type(value) != LauncherMessageType.ONETIME_SEND_OURS:
                continue
            bot_id, target = LauncherMessages.decode_onetime_send_ours(value)
            requests.append((bot_id, target, c.get_position(bld_id)))
        return requests

    def _find_adjacent_requester(
        self, c: Controller, bot_id_low12: int
    ) -> Position | None:
        my_team = c.get_team()
        for eid in c.get_nearby_entities(_ACTION_RADIUS_SQ):
            if c.get_entity_type(eid) != EntityType.BUILDER_BOT:
                continue
            if c.get_team(eid) != my_team:
                continue
            if (eid & _BOT_ID_MASK) != bot_id_low12:
                continue
            return c.get_position(eid)
        return None

    def _best_throw_tile_toward(
        self, c: Controller, bot_pos: Position, desired: Position
    ) -> Position | None:
        my_pos = c.get_position()
        best_d2 = (bot_pos.x - desired.x) ** 2 + (bot_pos.y - desired.y) ** 2
        best: Position | None = None
        for dx in range(-_THROW_SPAN, _THROW_SPAN + 1):
            for dy in range(-_THROW_SPAN, _THROW_SPAN + 1):
                if dx == 0 and dy == 0:
                    continue
                if dx * dx + dy * dy > _THROW_RANGE_SQ:
                    continue
                cand = Position(my_pos.x + dx, my_pos.y + dy)
                d2 = (cand.x - desired.x) ** 2 + (cand.y - desired.y) ** 2
                if d2 >= best_d2:
                    continue
                if not c.can_launch(bot_pos, cand):
                    continue
                best_d2 = d2
                best = cand
        return best

    def _find_throw_target(self, c: Controller) -> Position | None:
        roads = [
            c.get_position(bid)
            for bid in c.get_nearby_buildings()
            if c.get_entity_type(bid) == EntityType.ROAD
        ]

        if not roads:
            return None

        roads.sort(
            key=lambda pos: pos.distance_squared(
                self.core_pos if self.core_pos is not None else Position(0, 0)
            )
        )

        return roads[-1]

    def run(self, c: Controller):
        # Priority 1: serve any ONETIME_SEND_OURS request from an adjacent friendly,
        # throwing toward the requester's desired target.
        for bot_id_low12, desired, marker_pos in self._read_launch_requests(c):
            if bot_id_low12 in self._serviced_bot_ids:
                continue
            bot_pos = self._find_adjacent_requester(c, bot_id_low12)
            if bot_pos is None:
                continue
            throw_tile = self._best_throw_tile_toward(c, bot_pos, desired)
            if throw_tile is None:
                continue
            c.launch(bot_pos, throw_tile)
            self.idle_rounds = 0
            # Destroy is free and stackable; clear the request so we don't
            # reprocess it next tick. If the marker sits outside our r²≤2
            # destroy range, fall back to an in-memory blacklist.
            if c.can_destroy(marker_pos):
                c.destroy(marker_pos)
            else:
                self._serviced_bot_ids.add(bot_id_low12)
            print(
                f"Launched friendly {bot_id_low12} at {bot_pos} toward {desired} "
                f"via {throw_tile}"
            )
            return

        target = self._find_throw_target(c)
        nearby_enemies = [
            c.get_position(e)
            for e in c.get_nearby_entities(2)
            if c.get_team(e) != c.get_team()
            and c.get_entity_type(e) == EntityType.BUILDER_BOT
        ]

        if not nearby_enemies:
            self.idle_rounds += 1
            if self.idle_rounds > 50:
                c.self_destruct()
            return

        if target is None:
            print(f"Couldn't find a target for enemy at {nearby_enemies[0]}")
            self.idle_rounds += 1
            if self.idle_rounds > 200:
                c.self_destruct()
            return

        if c.can_launch(nearby_enemies[0], target):
            c.launch(nearby_enemies[0], target)
            self.idle_rounds = 0
            print(f"Launched bot at {nearby_enemies[0]} at {target}")
        else:
            self.idle_rounds += 1
            if self.idle_rounds > 50:
                c.self_destruct()
