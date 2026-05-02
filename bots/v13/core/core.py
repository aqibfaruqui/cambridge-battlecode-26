from cambc import Controller, EntityType, Position, ResourceType
from builders.builder import BuilderType
from utils.pathfinding.movement import on_map


_CONVERT_TITANIUM_THRESHOLD = 200
_AXIONITE_TO_TITANIUM_RATE = 4
_DISABLE_ATTACKERS = True
_DISABLE_HEALERS = True


class Core:
    def __init__(self):
        self.builders_spawned = 0
        self.default_spawn_plan = [
            BuilderType.HARVESTER_1,
            BuilderType.ATTACKER_REVAMPED,
            BuilderType.HARVESTER_2,
            BuilderType.ATTACKER_REVAMPED,
            # BuilderType.HARVESTER_3,
        ]
        self.spawn_plan = self.default_spawn_plan.copy()
        self.healer_id: int | None = None
        self.last_periodic_attacker_round = 0
        self.valid_axionite_spawn = 0
        self.axioniter_spawn_count = 0

    def _has_enemy_builder_bot_in_vision_unhandled(self, c: Controller) -> bool:
        my_team = c.get_team()
        ours = [
            bb
            for bb in c.get_nearby_units()
            if c.get_team(bb) == my_team
            and c.get_entity_type(bb) == EntityType.BUILDER_BOT
        ]
        enemies = [
            bb
            for bb in c.get_nearby_units()
            if c.get_team(bb) != my_team
            and c.get_entity_type(bb) == EntityType.BUILDER_BOT
        ]

        for e in enemies:
            if not any(
                c.get_position(e).distance_squared(c.get_position(o)) <= 2 for o in ours
            ):
                return True
        return False

    def _has_enemy_builder_bot_in_vision(self, c: Controller) -> bool:
        my_team = c.get_team()
        for eid in c.get_nearby_entities():
            if c.get_team(eid) == my_team:
                continue
            if c.get_entity_type(eid) == EntityType.BUILDER_BOT:
                return True
        return False

    def _builder_bots_on_core_ring_count(self, c: Controller) -> int:
        core_pos = c.get_position()
        count = 0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                p = Position(core_pos.x + dx, core_pos.y + dy)
                if not on_map(c, p):
                    continue
                if c.get_tile_builder_bot_id(p) is not None:
                    count += 1
        return count

    def _builders_on_core_allowed(self, c: Controller) -> int:
        my_id = c.get_id()
        hp = c.get_hp(my_id)
        max_hp = c.get_max_hp(my_id)
        if 5 * hp < 3 * max_hp:
            return 4
        if 5 * hp < 4 * max_hp:
            return 2
        return 0

    def _healer_alive(self, c: Controller) -> bool:
        if self.healer_id is None:
            return False
        return self.healer_id in c.get_nearby_units()

    def _try_spawn(self, c: Controller, builder_type: BuilderType) -> int | None:
        spawn_pos = builder_type.position_from_core(c.get_position())
        if not on_map(c, spawn_pos):
            return None
        if not c.can_spawn(spawn_pos):
            return None
        if (
            builder_type in {BuilderType.ATTACKER, BuilderType.ATTACKER_REVAMPED}
            and _DISABLE_ATTACKERS
        ):
            return 1
        elif builder_type == BuilderType.HEALER and _DISABLE_HEALERS:
            return 1
        return c.spawn_builder(spawn_pos)

    def _should_spawn_healer(self, c: Controller) -> bool:
        if not self._has_enemy_builder_bot_in_vision_unhandled(c):
            return False
        if self._builder_bots_on_core_ring_count(c) > self._builders_on_core_allowed(c):
            return False
        return True

    def _try_spawn_healer(self, c: Controller) -> bool:
        new_id = self._try_spawn(c, BuilderType.HEALER)
        if new_id is None:
            return False
        self.healer_id = new_id
        return True

    def _convert_axionite_if_low_titanium(self, c: Controller) -> None:
        titanium, axionite = c.get_global_resources()
        convertible_axionite = axionite - 51
        if titanium >= _CONVERT_TITANIUM_THRESHOLD or convertible_axionite <= 0:
            return

        deficit = _CONVERT_TITANIUM_THRESHOLD - titanium
        amount = min(
            convertible_axionite,
            (deficit + _AXIONITE_TO_TITANIUM_RATE - 1) // _AXIONITE_TO_TITANIUM_RATE,
        )
        if amount > 0:
            c.convert(amount)

    def _should_spawn_axioniter(self, c: Controller) -> bool:
        adjacent: set[Position] = set()
        me = c.get_position()
        x, y = me.x, me.y
        for dx in (-1, 0, 1):
            adjacent.add(Position(x + dx, y + 2))
        for dx in (-1, 0, 1):
            adjacent.add(Position(x + dx, y - 2))
        for dy in (-1, 0, 1):
            adjacent.add(Position(x + 2, y + dy))
        for dy in (-1, 0, 1):
            adjacent.add(Position(x - 2, y + dy))

        for conveyor in adjacent:
            if not on_map(c, conveyor):
                continue
            bid = c.get_tile_building_id(conveyor)
            if bid is None or c.get_entity_type(bid) != EntityType.CONVEYOR:
                continue

            dir_to_core = conveyor.direction_to(me)
            core_centre = conveyor.add(dir_to_core).add(dir_to_core)
            if (
                core_centre == me
                and c.get_stored_resource(bid) == ResourceType.TITANIUM
            ):
                return True

        return False

    def run(self, c: Controller):
        self._convert_axionite_if_low_titanium(c)

        self.valid_axionite_spawn -= 1
        if self.valid_axionite_spawn <= 0 and self._should_spawn_axioniter(c):
            self.valid_axionite_spawn = 4

        if self.valid_axionite_spawn > 0 and self.axioniter_spawn_count < 1:
            if self._try_spawn(c, BuilderType.AXIONITER) is not None:
                self.axioniter_spawn_count += 1
                return

        if c.get_current_round() in {1000, 1001}:
            self.spawn_plan = self.default_spawn_plan.copy()

        if self.builders_spawned < len(self.spawn_plan):
            builder_type = self.spawn_plan[self.builders_spawned]
            if (
                builder_type == BuilderType.ATTACKER_REVAMPED
                and self._should_spawn_healer(c)
                and self._try_spawn_healer(c)
            ):
                return
            if self._try_spawn(c, builder_type) is not None:
                self.builders_spawned += 1
            return

        if self._should_spawn_healer(c):
            self._try_spawn_healer(c)
            return

        round_now = c.get_current_round()
        if (
            round_now > 200
            and round_now - self.last_periodic_attacker_round >= 70
            and c.get_scale_percent() < 800
        ):
            if self._try_spawn(c, BuilderType.ATTACKER_REVAMPED) is not None:
                self.last_periodic_attacker_round = round_now
                return
