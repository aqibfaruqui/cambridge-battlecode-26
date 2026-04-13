from collections import defaultdict, deque

from cambc import Controller, Direction, EntityType, Position

_LOGISTICS = frozenset({EntityType.CONVEYOR, EntityType.BRIDGE, EntityType.SPLITTER})


def compute_reachable_to_core(c: Controller, core_pos: Position) -> set[tuple[int, int]]:
    """Return tiles that can direct resources into the allied core footprint."""
    width = c.get_map_width()
    height = c.get_map_height()
    team = c.get_team()

    incoming: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)

    # Controller tile reads are vision-limited; build graph from visible buildings only.
    for building_id in c.get_nearby_buildings():
        if c.get_team(building_id) != team:
            continue

        entity_type = c.get_entity_type(building_id)
        if entity_type not in _LOGISTICS:
            continue

        origin = c.get_position(building_id)

        out_pos: Position | None = None
        if entity_type == EntityType.BRIDGE:
            out_pos = c.get_bridge_target(building_id)
        elif entity_type in (EntityType.CONVEYOR, EntityType.SPLITTER):
            out_dir: Direction = c.get_direction(building_id)
            out_pos = origin.add(out_dir)

        if out_pos is None:
            continue
        if not (0 <= out_pos.x < width and 0 <= out_pos.y < height):
            continue

        incoming[(out_pos.x, out_pos.y)].append((origin.x, origin.y))

    reachable: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()

    for y in range(max(0, core_pos.y - 1), min(height, core_pos.y + 2)):
        for x in range(max(0, core_pos.x - 1), min(width, core_pos.x + 2)):
            key = (x, y)
            reachable.add(key)
            queue.append(key)

    while queue:
        key = queue.popleft()
        for origin in incoming.get(key, ()):
            if origin in reachable:
                continue
            reachable.add(origin)
            queue.append(origin)

    return reachable


def conveyor_connects_to_core(
    pos: Position,
    direction: Direction,
    reachable_to_core: set[tuple[int, int]],
) -> bool:
    out_pos = pos.add(direction)
    return (out_pos.x, out_pos.y) in reachable_to_core


def bridge_connects_to_core(
    target: Position,
    reachable_to_core: set[tuple[int, int]],
) -> bool:
    return (target.x, target.y) in reachable_to_core
