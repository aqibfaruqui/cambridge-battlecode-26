from cambc import Controller, EntityType

class Broadcaster:
    def __init__(self):
        self.broadcasts: list[int] = []
        self._curr = 0
        self._cd = 0
        self._max_pause = 4

    def run(self, c: Controller):
        if not self.broadcasts:
            return
        
        if self._cd > 0:
            self._cd -= 1
            return

        for tile in c.get_nearby_tiles(2):
            bid = c.get_tile_building_id(tile)
            our_marker = (
                bid is not None 
                and c.get_entity_type(bid) == EntityType.MARKER
                and c.get_team(bid) == c.get_team()
                and c.get_tile_builder_bot_id(tile) is None
            )

            if our_marker and c.can_destroy(tile):
                c.destroy(tile)
                
            if c.can_place_marker(tile):
                c.place_marker(tile, self.broadcasts[self._curr])
                self._curr += 1
                self._cd = self._max_pause
                self._curr %= len(self.broadcasts)
                break


    def add_broadcast(self, data: int):
        self.broadcasts.append(data)

    def clear_broadcasts(self):
        self.broadcasts.clear()
        self._curr = 0