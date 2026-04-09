from typing import Optional
from collections import deque

from nav.space_map import sm_in_bounds, passable_at, GotoTileRepresentation
from grid import DIRS
from cambc import Direction


def bfs_path(
    space_map: list[list[int]],
    start_sm: tuple[int, int],
    target_sm: tuple[int, int],
    *,
    directions: list[Direction] | None = None,
) -> list[Direction] | None:
    """BFS on the 9x9 vision grid from start_sm toward target_sm.

    Returns the full shortest path as a list of Directions, or None if
    the target is unreachable.

    If target_sm is outside the 9x9 grid, BFS explores all reachable cells
    and returns the path to the reachable cell closest to the target.
    """
    if not sm_in_bounds(start_sm):
        raise ValueError(f"Start {start_sm} is outside the 9x9 vision grid")

    if directions is None:
        directions = DIRS

    target_in_bounds = sm_in_bounds(target_sm)

    if target_in_bounds and start_sm == target_sm:
        return []

    if target_in_bounds and not passable_at(target_sm, space_map):
        return None

    q = deque()
    q.append(start_sm)
    parent: dict[tuple[int, int], tuple[tuple[int, int], Direction]] = {}
    seen = {start_sm}

    while q:
        cx, cy = q.popleft()
        for d in directions:
            ddx, ddy = d.delta()
            nx, ny = cx + ddx, cy + ddy
            if (nx, ny) in seen:
                continue
            if not sm_in_bounds((nx, ny)):
                continue
            if not passable_at((nx, ny), space_map):
                continue
            seen.add((nx, ny))
            parent[(nx, ny)] = ((cx, cy), d)
            if target_in_bounds and (nx, ny) == target_sm:
                return _reconstruct(parent, target_sm)
            q.append((nx, ny))

    if not target_in_bounds:
        return _closest_path(parent, seen, start_sm, target_sm)

    return None


def _reconstruct(
    parent: dict[tuple[int, int], tuple[tuple[int, int], Direction]],
    target: tuple[int, int],
) -> list[Direction]:
    path = []
    cell = target
    while cell in parent:
        cell, direction = parent[cell]
        path.append(direction)
    path.reverse()
    return path


def _closest_path(
    parent: dict[tuple[int, int], tuple[tuple[int, int], Direction]],
    seen: set[tuple[int, int]],
    start_sm: tuple[int, int],
    target_sm: tuple[int, int],
) -> list[Direction] | None:
    best_cell = None
    best_dist = (start_sm[0] - target_sm[0]) ** 2 + (start_sm[1] - target_sm[1]) ** 2
    for cell in seen:
        if cell == start_sm:
            continue
        dist = (cell[0] - target_sm[0]) ** 2 + (cell[1] - target_sm[1]) ** 2
        if dist < best_dist:
            best_dist = dist
            best_cell = cell
    if best_cell is None:
        return None
    return _reconstruct(parent, best_cell)
