from typing import Optional

from cambc import Controller, EntityType, Position
from world.comms.for_buildings import BuildingMessages, BuildingMessageType


class GlobalState:
    def __init__(self, *, track_core: bool = False, track_enemy_core: bool = False):
        self.track_core = track_core
        self.track_enemy_core = track_enemy_core

        # Track core
        self._core_pos = None

        # Track enemy core
        self._enemy_core_pos = None

    def __str__(self) -> str:
        return (
            f"GlobalState(core_pos={self._core_pos}, "
            f"enemy_core_pos={self._enemy_core_pos})"
        )

    def update(self, c: Controller):
        if self.track_core:
            self._update_core_pos(c)
        if self.track_enemy_core:
            self._update_enemy_core_pos(c)

        self._adjacent_positions = [
            tile for tile in c.get_nearby_tiles(2) if tile != c.get_position()
        ]

        self._cardinally_adjacent_positions = [
            tile for tile in c.get_nearby_tiles(1) if tile != c.get_position()
        ]

    def _update_core_pos(self, c: Controller):
        if self._core_pos is not None:
            return

        for building_id in c.get_nearby_buildings():
            if c.get_entity_type(building_id) == EntityType.CORE:
                self._core_pos = c.get_position(building_id)
                return

        nearby_core_messages = [
            BuildingMessages.decode_self_core_location(c.get_marker_value(m))
            for m in c.get_nearby_buildings()
            if c.get_team(m) == c.get_team()
            and c.get_entity_type(m) == EntityType.MARKER
            and BuildingMessages.is_building_message(c.get_marker_value(m))
            and BuildingMessages.get_message_type(c.get_marker_value(m))
            == BuildingMessageType.SELF_CORE_LOCATION
        ]

        if nearby_core_messages:
            self._core_pos = nearby_core_messages[0]

    def _update_enemy_core_pos(self, c: Controller):
        if self._enemy_core_pos is not None:
            return

        for building_id in c.get_nearby_buildings():
            if (
                c.get_entity_type(building_id) == EntityType.CORE
                and c.get_team(building_id) != c.get_team()
            ):
                self._enemy_core_pos = c.get_position(building_id)
                return

        nearby_enemy_core_messages = [
            BuildingMessages.decode_enemy_core_location(c.get_marker_value(m))
            for m in c.get_nearby_buildings()
            if c.get_team(m) == c.get_team()
            and c.get_entity_type(m) == EntityType.MARKER
            and BuildingMessages.is_building_message(c.get_marker_value(m))
            and BuildingMessages.get_message_type(c.get_marker_value(m))
            == BuildingMessageType.ENEMY_CORE_LOCATION
        ]

        if nearby_enemy_core_messages:
            self._enemy_core_pos = nearby_enemy_core_messages[0]

    def try_core_pos(self) -> Optional[Position]:
        return self._core_pos

    def get_core_pos(self) -> Position:
        if self._core_pos is None:
            raise RuntimeError(f"Core position not found, tracking? {self.track_core}")
        return self._core_pos

    def try_enemy_core_pos(self) -> Optional[Position]:
        return self._enemy_core_pos

    def get_enemy_core_pos(self) -> Position:
        if self._enemy_core_pos is None:
            raise RuntimeError(
                f"Enemy core position not found, tracking? {self.track_enemy_core}"
            )
        return self._enemy_core_pos
