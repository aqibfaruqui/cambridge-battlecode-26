#!/usr/bin/env python
"""Replay analysis CLI for Battlecode-26 Cambridge.

Five subcommands, one parsed-and-cached replay per invocation:

  grid    region snapshot at a specific turn
  trace   one bot's per-turn timeline (positions + stdout log)
  flow    per-tile resource-flow arrows over a turn window
  diff    chronological event log between two turns
  chain   walk a conveyor/bridge/splitter chain from a starting tile

The parsed replay is pickled under ``scripts/.replay_cache/`` keyed by
``(abspath, mtime)`` so repeated queries against the same replay don't repay
the protobuf-decode cost.

Cell legend (used by ``grid``)
  6-char cells, layout ``TT t d r``  where::

    TT  2-char entity / tile abbreviation
    t   team digit (0/1) or '.' for neutral
    d   direction glyph: ↑ ↗ → ↘ ↓ ↙ ← ↖ for the eight compass headings;
        '·' means no facing. Splitters (SP) show their facing arrow too —
        outputs are the T-shape (facing + ±90° perpendiculars).
    r   stored resource: T=titanium, a=raw axionite, R=refined axionite, '.'=none.

  Tiles with no entity show env codes: '..' empty, '==' wall, 'Ti' Ti ore,
  'Ax' Ax ore. A trailing '*' is appended to a cell when a builder bot stands
  on it (so each cell is up to 7 chars wide once the bot overlay is included).
"""

from __future__ import annotations

import argparse
import hashlib
import pickle
import sys
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "_generated"))
import cambc_pb2  # type: ignore[import-not-found]  # noqa: E402


# ---------------------------------------------------------------------------
# Constants

CACHE_DIR = HERE / ".replay_cache"
CACHE_VERSION = 3  # bump when ParsedReplay schema changes

# Direction enum from proto: 0=CENTRE, 1=N, 2=NE, 3=E, 4=SE, 5=S, 6=SW, 7=W, 8=NW
_DIR_DXDY: dict[int, tuple[int, int]] = {
    0: (0, 0),
    1: (0, -1), 2: (1, -1), 3: (1, 0), 4: (1, 1),
    5: (0, 1), 6: (-1, 1), 7: (-1, 0), 8: (-1, -1),
}
_DIR_NAME = {0: "C", 1: "N", 2: "NE", 3: "E", 4: "SE", 5: "S", 6: "SW", 7: "W", 8: "NW"}
_DIR_ARROW = {0: "·", 1: "↑", 2: "↗", 3: "→", 4: "↘", 5: "↓", 6: "↙", 7: "←", 8: "↖"}

_ENV_CELL = {0: "..", 1: "==", 2: "Ti", 3: "Ax"}

_RES_CHAR = {0: ".", 1: "T", 2: "a", 3: "R"}  # TI / RAW_AX / REFINED_AX
_RES_NAME = {0: "NONE", 1: "TI", 2: "AX_RAW", 3: "AX_REF"}

_KIND_ABBR = {
    "builder_bot": "BB", "conveyor": "CV", "splitter": "SP",
    "armoured_conveyor": "AC", "bridge": "BR", "harvester": "HV",
    "foundry": "FD", "road": "RD", "barrier": "XX", "marker": "MK",
    "core": "CR", "gunner": "GN", "sentinel": "SN", "breach": "BC",
    "launcher": "LN",
}

# Entity kinds that occupy a tile exclusively (only one such per tile).
_BUILDING_KINDS = {
    "conveyor", "splitter", "armoured_conveyor", "bridge", "harvester",
    "foundry", "road", "barrier", "marker", "core",
    "gunner", "sentinel", "breach", "launcher",
}

# Kinds that store a resource and report it via .stored.
_STORED_KINDS = {"conveyor", "splitter", "armoured_conveyor", "bridge", "foundry"}

# Conveyor-like kinds that have a single facing and step a single tile downstream.
_CONVEYOR_KINDS = {"conveyor", "armoured_conveyor"}


# ---------------------------------------------------------------------------
# Replay parsing & caching

@dataclass
class Entity:
    eid: int
    kind: str
    team: int
    pos: tuple[int, int]
    hp: int
    max_hp: int
    direction: Optional[int] = None
    bridge_target: Optional[tuple[int, int]] = None
    stored: Optional[int] = None
    resource_type: Optional[int] = None  # harvester
    ammo_type: Optional[int] = None
    ammo_amount: Optional[int] = None
    marker_value: Optional[int] = None


@dataclass
class ParsedReplay:
    """Parsed, indexed replay.

    The ``turns`` field is a list of per-turn event lists. Each event is a
    tuple ``(kind, payload_dict)``. We deliberately keep this denormalised so
    that subcommands that need event-stream semantics (``flow``, ``diff``) can
    iterate without rehydrating protobuf messages.
    """
    width: int
    height: int
    env: list[list[int]]  # env[y][x]
    cores: list[Entity]
    turns: list[list[tuple[str, dict]]]
    # Pre-indexed for trace/grid hot paths
    bot_stdout: dict[int, dict[int, str]]   # bot_id -> turn -> first matching stdout line
    bot_full_stdout: dict[int, dict[int, str]]  # bot_id -> turn -> full stdout
    bot_pos_after: dict[int, dict[int, tuple[int, int]]]  # bot_id -> turn -> position at turn end
    bot_initial_pos: dict[int, tuple[int, int]]
    bot_team: dict[int, int]
    cache_version: int = CACHE_VERSION


def _entity_payload(ent) -> dict:
    """Convert a protobuf Entity into a plain dict (cache-safe)."""
    kind = ent.WhichOneof("kind")
    out: dict[str, Any] = {
        "id": ent.id,
        "kind": kind,
        "team": int(ent.team),
        "pos": (ent.position.x, ent.position.y),
        "hp": ent.hp,
        "max_hp": ent.max_hp,
    }
    if kind in ("conveyor", "splitter", "armoured_conveyor"):
        sub = getattr(ent, kind)
        out["direction"] = int(sub.direction)
        out["stored"] = int(sub.stored)
    elif kind == "bridge":
        out["bridge_target"] = (ent.bridge.target.x, ent.bridge.target.y)
        out["stored"] = int(ent.bridge.stored)
    elif kind == "harvester":
        out["resource_type"] = int(ent.harvester.resource_type)
    elif kind == "foundry":
        out["stored"] = int(ent.foundry.stored)
    elif kind in ("gunner", "sentinel", "breach"):
        sub = getattr(ent, kind)
        out["direction"] = int(sub.direction)
        out["ammo_type"] = int(sub.ammo_type)
        out["ammo_amount"] = sub.ammo_amount
    elif kind == "launcher":
        out["ammo_type"] = int(ent.launcher.ammo_type)
        out["ammo_amount"] = ent.launcher.ammo_amount
    elif kind == "marker":
        out["marker_value"] = ent.marker.value
    return out


def _parse_replay(path: Path) -> ParsedReplay:
    """Decode the replay file from disk into a ParsedReplay.

    Eager: walks every turn once. ~6 MB file decodes in ~1 s on a laptop.
    """
    raw = path.read_bytes()
    msg = cambc_pb2.Replay()
    msg.ParseFromString(raw)

    env = [[0] * msg.map.width for _ in range(msg.map.height)]
    for y, row in enumerate(msg.map.rows):
        for x, t in enumerate(row.tiles):
            env[y][x] = int(t)

    cores: list[Entity] = []
    for c in msg.map.cores:
        cores.append(Entity(
            eid=c.id, kind="core", team=int(c.team),
            pos=(c.position.x, c.position.y), hp=0, max_hp=0,
        ))

    turns: list[list[tuple[str, dict]]] = []
    bot_stdout: dict[int, dict[int, str]] = defaultdict(dict)
    bot_full_stdout: dict[int, dict[int, str]] = defaultdict(dict)
    bot_pos_after: dict[int, dict[int, tuple[int, int]]] = defaultdict(dict)
    bot_initial_pos: dict[int, tuple[int, int]] = {}
    bot_team: dict[int, int] = {}

    # For pos-after-turn tracking we need to know each bot's last position at
    # the end of each turn — initialise from PlaceEntity, update on MoveBuilderBot.
    last_pos: dict[int, tuple[int, int]] = {}

    for turn_idx, turn in enumerate(msg.turns):
        events: list[tuple[str, dict]] = []
        for upd in turn.updates:
            kind = upd.WhichOneof("kind")
            if kind == "place_entity":
                e = upd.place_entity.entity
                payload = _entity_payload(e)
                events.append(("place", payload))
                if payload["kind"] == "builder_bot":
                    bot_initial_pos.setdefault(e.id, payload["pos"])
                    bot_team.setdefault(e.id, payload["team"])
                    last_pos[e.id] = payload["pos"]
            elif kind == "move_builder_bot":
                mv = upd.move_builder_bot
                pos = (mv.to.x, mv.to.y)
                events.append(("move", {"id": mv.id, "to": pos}))
                last_pos[mv.id] = pos
            elif kind == "remove_entity":
                rid = upd.remove_entity.id
                events.append(("remove", {"id": rid}))
            elif kind == "distribute_resources":
                moves = []
                for m in upd.distribute_resources.moves:
                    src = getattr(m, "from")
                    moves.append({
                        "src": (src.x, src.y),
                        "dst": (m.to.x, m.to.y),
                        "rid": m.resource_id if m.HasField("resource_id") else None,
                    })
                events.append(("flow", {"moves": moves}))
            elif kind == "update_hp":
                u = upd.update_hp
                events.append(("hp", {"id": u.id, "delta": u.delta}))
            elif kind == "update_players":
                p = upd.update_players.players
                events.append(("players", {
                    "a": {"ti": p.a.titanium, "ax": p.a.axionite,
                          "ti_mined": p.a.titanium_collected,
                          "ax_mined": p.a.axionite_collected},
                    "b": {"ti": p.b.titanium, "ax": p.b.axionite,
                          "ti_mined": p.b.titanium_collected,
                          "ax_mined": p.b.axionite_collected},
                }))
            elif kind == "set_action_cooldown":
                pass  # not surfaced — keep parser cheap
            elif kind == "set_move_cooldown":
                pass
            elif kind == "bot_output":
                bo = upd.bot_output
                stdout = bo.stdout or ""
                if stdout:
                    bot_full_stdout[bo.id][turn_idx] = stdout
                    # Capture the bot's own log line if it printed one. The
                    # axioniter / harvester bots tag lines with [<role> <id>].
                    tag = f" {bo.id}]"
                    for ln in stdout.splitlines():
                        if tag in ln and ln.startswith("[") and ln.find("]") != -1:
                            bot_stdout[bo.id][turn_idx] = ln
                            break
                events.append(("stdout", {"id": bo.id, "exec_us": bo.exec_time_us, "tled": bo.tled}))
            elif kind == "indicator_line":
                il = upd.indicator_line
                events.append(("ind_line", {
                    "id": il.id,
                    "a": (il.pos_a.x, il.pos_a.y),
                    "b": (il.pos_b.x, il.pos_b.y),
                    "rgb": (il.r, il.g, il.b),
                }))
            elif kind == "indicator_dot":
                idot = upd.indicator_dot
                events.append(("ind_dot", {
                    "id": idot.id,
                    "pos": (idot.pos.x, idot.pos.y),
                    "rgb": (idot.r, idot.g, idot.b),
                }))
            elif kind == "fire_turret":
                ft = upd.fire_turret
                events.append(("fire", {
                    "src": (getattr(ft, "from").x, getattr(ft, "from").y),
                    "dst": (ft.to.x, ft.to.y),
                }))
            elif kind == "builder_attack":
                events.append(("battack", {"id": upd.builder_attack.id}))
        turns.append(events)
        # Snapshot end-of-turn positions for any bot we know about (only
        # those that moved or placed this turn appear in last_pos updates;
        # carry forward implicitly when querying via bot_pos_after).
        for bid, pos in last_pos.items():
            bot_pos_after[bid][turn_idx] = pos

    return ParsedReplay(
        width=msg.map.width,
        height=msg.map.height,
        env=env,
        cores=cores,
        turns=turns,
        bot_stdout=dict(bot_stdout),
        bot_full_stdout=dict(bot_full_stdout),
        bot_pos_after=dict(bot_pos_after),
        bot_initial_pos=bot_initial_pos,
        bot_team=bot_team,
    )


def load_replay(path: str) -> ParsedReplay:
    """Load a replay, hitting the on-disk cache when possible."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        sys.exit(f"replay not found: {p}")
    mtime = p.stat().st_mtime_ns
    key = hashlib.sha256(f"{p}::{mtime}::{CACHE_VERSION}".encode()).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{key}.pkl"
    if cache_path.exists():
        try:
            with cache_path.open("rb") as f:
                obj: ParsedReplay = pickle.load(f)
            if obj.cache_version == CACHE_VERSION:
                return obj
        except Exception:
            pass  # fall through and reparse
    obj = _parse_replay(p)
    try:
        with cache_path.open("wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return obj


# ---------------------------------------------------------------------------
# State materialisation

def _state_at(replay: ParsedReplay, turn: int) -> tuple[dict[int, dict], dict[tuple[int, int], int]]:
    """Reconstruct end-of-turn state (entities by id, building by tile).

    O(events_up_to_turn). For 2 000 turns × ~300 events = ~600 k ops; well
    under a second on the test replay. Builder bots are tracked in
    ``entities`` but are NOT placed in ``tile`` (they overlay buildings).

    Tracks ``stored`` per-tile by replaying ``flow`` events: each move drains
    the source's stored and fills the destination's. Without this, ``stored``
    would only ever reflect the value at PlaceEntity time (almost always
    NONE), since the engine never broadcasts stored-changed updates.
    """
    if turn < 0:
        return {}, {}
    last_idx = min(turn, len(replay.turns) - 1)
    entities: dict[int, dict] = {}
    tile: dict[tuple[int, int], int] = {}
    for c in replay.cores:
        entities[c.eid] = {
            "id": c.eid, "kind": "core", "team": c.team,
            "pos": c.pos, "hp": 0, "max_hp": 0,
        }
        tile[c.pos] = c.eid
    for tn in range(last_idx + 1):
        for kind, p in replay.turns[tn]:
            if kind == "place":
                entities[p["id"]] = dict(p)
                if p["kind"] in _BUILDING_KINDS:
                    tile[p["pos"]] = p["id"]
            elif kind == "remove":
                e = entities.pop(p["id"], None)
                if e is not None and e["kind"] in _BUILDING_KINDS:
                    if tile.get(e["pos"]) == p["id"]:
                        del tile[e["pos"]]
            elif kind == "move":
                e = entities.get(p["id"])
                if e is not None:
                    e["pos"] = p["to"]
            elif kind == "flow":
                for mv in p["moves"]:
                    _apply_flow_to_state(mv["src"], mv["dst"], entities, tile)
    return entities, tile


def _resource_type_at(pos: tuple[int, int],
                      entities: dict[int, dict],
                      tile: dict[tuple[int, int], int]) -> int:
    """Best-effort: what ResourceType is currently moving out of ``pos``?

    Harvesters: their fixed ``resource_type``. Foundries: refined axionite
    (foundries consume Ti+raw_ax and emit refined). Other transports: whatever
    we last tracked into their ``stored``.
    """
    eid = tile.get(pos)
    if eid is None:
        return 0
    e = entities[eid]
    kind = e["kind"]
    if kind == "harvester":
        return e.get("resource_type") or 0
    if kind == "foundry":
        # Foundry stored is whichever resource was last placed in it; the only
        # resource it produces (and therefore the only thing that can flow OUT
        # of a foundry tile) is REFINED_AXIONITE.
        return 3
    return e.get("stored") or 0


def _apply_flow_to_state(src: tuple[int, int], dst: tuple[int, int],
                         entities: dict[int, dict],
                         tile: dict[tuple[int, int], int]) -> int:
    """Update ``stored`` on src and dst tiles. Returns the inferred type."""
    res_type = _resource_type_at(src, entities, tile)
    src_eid = tile.get(src)
    if src_eid is not None:
        se = entities[src_eid]
        # Harvesters produce continuously, so they "refill" — leave their
        # stored alone. Foundries are a black box for our purposes; leave too.
        if se["kind"] not in ("harvester", "foundry"):
            se["stored"] = 0
    dst_eid = tile.get(dst)
    if dst_eid is not None:
        de = entities[dst_eid]
        # Mark the destination's stored only on transports that actually carry
        # a resource (the foundry and core do too, but updating stored on a
        # foundry conflates Ti/raw-Ax inputs).
        if de["kind"] in ("conveyor", "splitter", "armoured_conveyor", "bridge"):
            de["stored"] = res_type
    return res_type


def _bots_at_tile(entities: dict[int, dict]) -> dict[tuple[int, int], list[int]]:
    out: dict[tuple[int, int], list[int]] = defaultdict(list)
    for eid, e in entities.items():
        if e["kind"] == "builder_bot":
            out[e["pos"]].append(eid)
    return out


# ---------------------------------------------------------------------------
# Cell rendering (grid)

def _step_to_dir(dx: int, dy: int) -> int:
    """Reduce a delta to the matching 8-direction enum (0 if zero/non-orthogonal)."""
    sx = 0 if dx == 0 else (1 if dx > 0 else -1)
    sy = 0 if dy == 0 else (1 if dy > 0 else -1)
    for k, (kdx, kdy) in _DIR_DXDY.items():
        if (kdx, kdy) == (sx, sy) and k != 0:
            return k
    return 0


def _bridge_dir_glyph(src: tuple[int, int], dst: tuple[int, int]) -> str:
    return _DIR_ARROW.get(_step_to_dir(dst[0] - src[0], dst[1] - src[1]), "·")


def _cell_for(env_t: int, eid: Optional[int], entities: dict[int, dict]) -> str:
    """Render a 6-char cell.

    Layout:  TT t d r .   (the trailing dot becomes '*' if a bot overlays).
    Tiles with no entity show env codes ('..', '==', 'Ti', 'Ax') padded.
    """
    if eid is None:
        # Empty / wall / ore tile
        env_cell = _ENV_CELL.get(env_t, "??")
        return f"{env_cell}....".ljust(6)

    e = entities[eid]
    kind = e["kind"]
    abbr = _KIND_ABBR.get(kind, "??")
    team = str(e["team"]) if e["team"] in (0, 1) else "."
    direction = "·"
    stored = "·"
    if kind in _CONVEYOR_KINDS:
        direction = _DIR_ARROW.get(e.get("direction") or 0, "·")
        stored = _RES_CHAR.get(e.get("stored") or 0, ".")
    elif kind == "splitter":
        # Splitter shows facing as an arrow; the type abbreviation 'SP'
        # tells the reader it fans into a T-shape relative to that facing.
        direction = _DIR_ARROW.get(e.get("direction") or 0, "·")
        stored = _RES_CHAR.get(e.get("stored") or 0, ".")
    elif kind == "bridge":
        direction = _bridge_dir_glyph(e["pos"], e["bridge_target"])
        stored = _RES_CHAR.get(e.get("stored") or 0, ".")
    elif kind in ("gunner", "sentinel", "breach"):
        direction = _DIR_ARROW.get(e.get("direction") or 0, "·")
        stored = _RES_CHAR.get(e.get("ammo_type") or 0, ".")
    elif kind == "launcher":
        stored = _RES_CHAR.get(e.get("ammo_type") or 0, ".")
    elif kind == "foundry":
        stored = _RES_CHAR.get(e.get("stored") or 0, ".")
    elif kind == "harvester":
        stored = _RES_CHAR.get(e.get("resource_type") or 0, ".")
    return f"{abbr}{team}{direction}{stored} ".ljust(6)


def _resolve_region(
    replay: ParsedReplay,
    region: Optional[tuple[int, int, int, int]],
    full_default: bool = False,
) -> tuple[int, int, int, int]:
    if region is not None:
        x1, y1, x2, y2 = region
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(replay.width - 1, x2); y2 = min(replay.height - 1, y2)
        return x1, y1, x2, y2
    if full_default:
        return 0, 0, replay.width - 1, replay.height - 1
    # Default region: a 12x12 window, top-left of the map.
    return 0, 0, min(11, replay.width - 1), min(11, replay.height - 1)


# ---------------------------------------------------------------------------
# Subcommand: grid

def cmd_grid(replay: ParsedReplay, args) -> None:
    region = _resolve_region(replay, args.region, full_default=args.full)
    x1, y1, x2, y2 = region

    entities, tile = _state_at(replay, args.turn)
    bots = _bots_at_tile(entities)

    print(f"# grid  turn={args.turn}  region=({x1},{y1})..({x2},{y2})")
    print(f"# legend: TT t d r [*=bot]   d=facing (↑↗→↘↓↙←↖, ·=none; SP fans T-shape from facing)")
    print(f"#        types: BB=bot CV=conv SP=splitter AC=armoured BR=bridge HV=harvester")
    print(f"#               FD=foundry RD=road CR=core MK=marker GN=gun SN=sentinel")
    print(f"#               BC=breach LN=launcher  ..=empty ==wall Ti/Ax=ore")
    print()

    # Column headers
    print("    " + " ".join(f"{x:>6}" for x in range(x1, x2 + 1)))
    for y in range(y1, y2 + 1):
        cells = []
        for x in range(x1, x2 + 1):
            eid = tile.get((x, y))
            cell = _cell_for(replay.env[y][x], eid, entities)
            if (x, y) in bots:
                cell = cell[:5] + "*"
            cells.append(cell)
        print(f"y={y:>2} " + " ".join(cells))

    # Per-tile bot rows showing IDs (bots can stack? typically one per tile)
    if bots:
        print()
        print("# bots in region:")
        for (bx, by), ids in sorted(bots.items()):
            if x1 <= bx <= x2 and y1 <= by <= y2:
                team_tags = [f"#{i}@t{entities[i]['team']}" for i in ids]
                print(f"  ({bx},{by}): {' '.join(team_tags)}")


# ---------------------------------------------------------------------------
# Subcommand: trace

def cmd_trace(replay: ParsedReplay, args) -> None:
    bot = args.bot
    a, b = args.turns
    a = max(0, a); b = min(len(replay.turns) - 1, b)
    if bot not in replay.bot_team:
        print(f"# bot {bot}: not found in this replay (known: "
              f"{sorted(replay.bot_team)[:20]}{'...' if len(replay.bot_team) > 20 else ''})")
        return

    team = replay.bot_team[bot]
    spawn = replay.bot_initial_pos.get(bot)
    print(f"# trace bot {bot}  team={team}  spawn={spawn}  turns=[{a}..{b}]")
    print(f"#  fields: t<turn>  pos=(x,y)  log='[role id] r=... state=...'")
    print()

    # Carry-forward end-of-turn position
    pos_index = replay.bot_pos_after.get(bot, {})
    last_pos: Optional[tuple[int, int]] = spawn
    for tn in range(a, b + 1):
        if tn in pos_index:
            last_pos = pos_index[tn]
        log = replay.bot_stdout.get(bot, {}).get(tn)
        line = f"t{tn:4d}  pos={last_pos}"
        if log:
            line += f"  {log}"
        elif args.full and tn in replay.bot_full_stdout.get(bot, {}):
            # Show a summary of the full stdout if the role-tagged line wasn't found
            text = replay.bot_full_stdout[bot][tn].strip().splitlines()[0]
            line += f"  raw={text!r}"
        print(line)


# ---------------------------------------------------------------------------
# Subcommand: flow

def _in_region(p: tuple[int, int], region: tuple[int, int, int, int]) -> bool:
    x1, y1, x2, y2 = region
    return x1 <= p[0] <= x2 and y1 <= p[1] <= y2


_RES_LABEL = {0: "??", 1: "Ti", 2: "Ax", 3: "Rx"}


def cmd_flow(replay: ParsedReplay, args) -> None:
    """Per-tile resource-flow histogram over a turn window.

    To attach a ResourceType to each flow we have to infer it: the protobuf
    only carries optional resource_id, never the type. We replay state up to
    the start of the window, then walk the window's flow events in order,
    treating each move's source-tile state as the type of resource moving.
    Updates to ``stored`` propagate as flows happen, so a chain of conveyors
    that started empty gets typed correctly the first time any resource
    enters it.
    """
    region = _resolve_region(replay, args.region, full_default=args.full)
    x1, y1, x2, y2 = region
    a, b = args.turns
    a = max(0, a); b = min(len(replay.turns) - 1, b)

    # Replay state up to (and including) ``a-1`` so the window starts hot.
    entities, tile = _state_at(replay, a - 1)

    # (x, y, glyph, res_type) -> count
    out_counts: dict[tuple[int, int, str, int], int] = defaultdict(int)
    in_counts: dict[tuple[int, int, str, int], int] = defaultdict(int)
    edges: dict[tuple[tuple[int, int], tuple[int, int], int], int] = defaultdict(int)

    for tn in range(a, b + 1):
        for kind, p in replay.turns[tn]:
            if kind == "place":
                entities[p["id"]] = dict(p)
                if p["kind"] in _BUILDING_KINDS:
                    tile[p["pos"]] = p["id"]
                continue
            if kind == "remove":
                e = entities.pop(p["id"], None)
                if e is not None and e["kind"] in _BUILDING_KINDS:
                    if tile.get(e["pos"]) == p["id"]:
                        del tile[e["pos"]]
                continue
            if kind == "move":
                e = entities.get(p["id"])
                if e is not None:
                    e["pos"] = p["to"]
                continue
            if kind != "flow":
                continue
            for mv in p["moves"]:
                src, dst = mv["src"], mv["dst"]
                # Resolve type *before* updating state so we read the source
                # as it was when this resource left it.
                res_type = _apply_flow_to_state(src, dst, entities, tile)
                if not (_in_region(src, region) or _in_region(dst, region)):
                    continue
                glyph = _DIR_ARROW.get(_step_to_dir(dst[0] - src[0], dst[1] - src[1]), "·")
                edges[(src, dst, res_type)] += 1
                if _in_region(src, region):
                    out_counts[(src[0], src[1], glyph, res_type)] += 1
                if _in_region(dst, region):
                    in_counts[(dst[0], dst[1], glyph, res_type)] += 1

    total = sum(edges.values())
    by_type: dict[int, int] = defaultdict(int)
    for key, n in edges.items():
        by_type[key[2]] += n
    type_breakdown = ", ".join(f"{_RES_LABEL[rt]}×{n}" for rt, n in sorted(by_type.items()))

    print(f"# flow turns=[{a}..{b}]  region=({x1},{y1})..({x2},{y2})")
    print(f"# total moves: {total} across {len(edges)} (src,dst,type) tuples [{type_breakdown}]")
    print()
    print("# per-tile outgoing flow (arrow + type × count):")
    by_tile: dict[tuple[int, int], list[tuple[str, int, int]]] = defaultdict(list)
    for (x, y, g, rt), n in out_counts.items():
        by_tile[(x, y)].append((g, rt, n))
    for (x, y) in sorted(by_tile):
        parts = ", ".join(
            f"{g}{_RES_LABEL[rt]}×{n}"
            for g, rt, n in sorted(by_tile[(x, y)], key=lambda t: -t[2])
        )
        print(f"  ({x:>2},{y:>2})  {parts}")

    if args.edges:
        print()
        print("# top edges (src → dst : type × count):")
        for (src, dst, rt), n in sorted(edges.items(), key=lambda t: -t[1])[:30]:
            print(f"  {src} → {dst}  {_RES_LABEL[rt]}×{n}")


# ---------------------------------------------------------------------------
# Subcommand: diff

_DIFF_KIND_FILTER = {
    "place", "remove", "move", "hp", "ind_dot", "ind_line",
    "fire", "battack", "stdout", "flow",
}


def _format_event(kind: str, p: dict, entities: dict[int, dict]) -> Optional[str]:
    if kind == "place":
        e = p
        extra = []
        if "direction" in e and e["direction"] is not None:
            extra.append(f"dir={_DIR_NAME.get(e['direction'])}")
        if "bridge_target" in e and e["bridge_target"] is not None:
            extra.append(f"target={e['bridge_target']}")
        if "stored" in e and e["stored"]:
            extra.append(f"stored={_RES_NAME.get(e['stored'])}")
        if "resource_type" in e and e["resource_type"]:
            extra.append(f"resource={_RES_NAME.get(e['resource_type'])}")
        suffix = "  " + " ".join(extra) if extra else ""
        return f"PLACE  id={e['id']:>4} t={e['team']} {e['kind']:<18} pos={e['pos']}{suffix}"
    if kind == "remove":
        e = entities.get(p["id"])
        if e is None:
            return f"REMOVE id={p['id']:>4} (unknown)"
        return f"REMOVE id={p['id']:>4} t={e['team']} {e['kind']:<18} pos={e['pos']}"
    if kind == "move":
        e = entities.get(p["id"])
        team = e["team"] if e else "?"
        return f"MOVE   id={p['id']:>4} t={team} -> {p['to']}"
    if kind == "hp":
        e = entities.get(p["id"])
        team = e["team"] if e else "?"
        ekind = e["kind"] if e else "?"
        return f"HP     id={p['id']:>4} t={team} {ekind} delta={p['delta']:+d}"
    if kind == "fire":
        return f"FIRE   {p['src']} -> {p['dst']}"
    if kind == "battack":
        e = entities.get(p["id"])
        team = e["team"] if e else "?"
        return f"BATTK  id={p['id']:>4} t={team}"
    if kind == "ind_dot":
        return f"DOT    bot={p['id']:>4} pos={p['pos']} rgb={p['rgb']}"
    if kind == "ind_line":
        return f"LINE   bot={p['id']:>4} {p['a']} -> {p['b']} rgb={p['rgb']}"
    if kind == "flow":
        return None  # handled separately to keep diff terse
    if kind == "stdout":
        return None
    return None


def cmd_diff(replay: ParsedReplay, args) -> None:
    a, b = args.turn_a, args.turn_b
    if a > b:
        a, b = b, a
    a = max(0, a); b = min(len(replay.turns) - 1, b)
    region = _resolve_region(replay, args.region, full_default=True)

    print(f"# diff turns t{a}..t{b}  region=({region[0]},{region[1]})..({region[2]},{region[3]})")
    if args.kinds:
        print(f"# filter kinds: {','.join(args.kinds)}")
    print()

    # Replay state turn-by-turn so we can resolve removed-entity metadata.
    entities, _ = _state_at(replay, max(0, a - 1))
    kinds = set(args.kinds) if args.kinds else _DIFF_KIND_FILTER
    for tn in range(a, b + 1):
        printed_header = False
        for kind, p in replay.turns[tn]:
            # Update state regardless of region/kind so subsequent events
            # can resolve entity metadata correctly.
            if kind == "place":
                entities[p["id"]] = dict(p)
            elif kind == "remove":
                pass  # keep entity around for the formatter, prune below
            elif kind == "move":
                e = entities.get(p["id"])
                if e is not None:
                    e["pos"] = p["to"]

            if kind not in kinds:
                if kind == "remove":
                    entities.pop(p["id"], None)
                continue

            # Region filter: drop events whose involved tile is outside.
            pos_for_filter: Optional[tuple[int, int]] = None
            if kind in ("place",):
                pos_for_filter = p["pos"]
            elif kind == "remove":
                e = entities.get(p["id"])
                pos_for_filter = e["pos"] if e else None
            elif kind == "move":
                pos_for_filter = p["to"]
            elif kind == "fire":
                pos_for_filter = p["src"]
            elif kind in ("ind_dot",):
                pos_for_filter = p["pos"]
            elif kind == "ind_line":
                pos_for_filter = p["a"]
            elif kind == "hp":
                e = entities.get(p["id"])
                pos_for_filter = e["pos"] if e else None
            in_region = pos_for_filter is None or _in_region(pos_for_filter, region)

            if in_region:
                line = _format_event(kind, p, entities)
                if line:
                    if not printed_header:
                        print(f"--- t{tn} ---")
                        printed_header = True
                    print(f"  {line}")

            if kind == "remove":
                entities.pop(p["id"], None)


# ---------------------------------------------------------------------------
# Subcommand: chain

def _conveyor_outputs(e: dict) -> list[tuple[int, int]]:
    """Return list of downstream tiles a transport entity feeds into."""
    src = e["pos"]
    if e["kind"] == "bridge":
        t = e.get("bridge_target")
        return [t] if t is not None else []
    direction = e.get("direction")
    if direction is None or direction == 0:
        return []
    dx, dy = _DIR_DXDY[direction]
    if e["kind"] == "splitter":
        # T-shape: facing + perpendicular ±2-rotations (90° on each side).
        # Equivalently, (dx, dy) plus the two perpendiculars (-dy, dx) and (dy, -dx).
        return [
            (src[0] + dx, src[1] + dy),
            (src[0] - dy, src[1] + dx),
            (src[0] + dy, src[1] - dx),
        ]
    return [(src[0] + dx, src[1] + dy)]


def _conveyor_inputs(tile_pos: tuple[int, int], entities: dict[int, dict]) -> list[int]:
    """Return entity ids of transports that feed into ``tile_pos``."""
    feeders: list[int] = []
    for eid, e in entities.items():
        if e["kind"] not in ("conveyor", "splitter", "armoured_conveyor", "bridge"):
            continue
        if tile_pos in _conveyor_outputs(e):
            feeders.append(eid)
    return feeders


def _harvester_consumers(harv_pos: tuple[int, int],
                         entities: dict[int, dict],
                         tile: dict[tuple[int, int], int]) -> list[tuple[int, int]]:
    """Adjacent transport tiles that pull resources OUT of this harvester.

    A harvester has no facing; the engine ships its output to adjacent
    transports that are *not* themselves directed back into the harvester.
    Restricted to 4-connected neighbours since conveyors are 4-way.
    """
    out: list[tuple[int, int]] = []
    for d in (1, 3, 5, 7):
        dx, dy = _DIR_DXDY[d]
        adj = (harv_pos[0] + dx, harv_pos[1] + dy)
        eid = tile.get(adj)
        if eid is None:
            continue
        e = entities[eid]
        if e["kind"] not in ("conveyor", "splitter", "armoured_conveyor", "bridge"):
            continue
        # Skip transports whose own output points back at this harvester —
        # they're inputs, not consumers.
        if harv_pos in _conveyor_outputs(e):
            continue
        out.append(adj)
    return out


def cmd_chain(replay: ParsedReplay, args) -> None:
    entities, tile = _state_at(replay, args.turn)
    start = tuple(args.start)
    if start not in tile:
        print(f"# no building at {start} at turn {args.turn} — nothing to follow.")
        return
    direction_label = "upstream" if args.upstream else "downstream"
    print(f"# chain  turn={args.turn}  start={start}  direction={direction_label}  depth={args.depth}")
    print(f"# fields: depth  pos      kind          team dir  stored")
    print()

    visited: set[tuple[int, int]] = set()

    def describe(e: dict) -> str:
        kind = e["kind"]
        team = e["team"]
        direction_glyph = "·"
        if kind == "bridge":
            direction_glyph = f"→{e.get('bridge_target')}"
        elif kind == "harvester":
            # Harvester emits whatever resource_type it mines; show that
            # in place of a facing arrow so the chain head is self-explanatory.
            rt = e.get("resource_type") or 0
            direction_glyph = f"prod={_RES_NAME.get(rt, '?')}"
        elif "direction" in e and e["direction"] is not None:
            direction_glyph = _DIR_ARROW.get(e["direction"], "?")
        stored = "·"
        if kind in _STORED_KINDS:
            stored = _RES_NAME.get(e.get("stored") or 0, "·")
        elif kind == "harvester":
            stored = _RES_NAME.get(e.get("resource_type") or 0, "·")
        return f"{kind:<18} t={team} dir={direction_glyph:<14} stored={stored}"

    def walk(pos: tuple[int, int], depth: int) -> None:
        if depth > args.depth:
            return
        if pos in visited:
            print("  " * depth + f"({pos[0]:>2},{pos[1]:>2}) [cycle]")
            return
        visited.add(pos)
        eid = tile.get(pos)
        if eid is None:
            print("  " * depth + f"({pos[0]:>2},{pos[1]:>2}) [empty/wall/ore — chain ends]")
            return
        e = entities[eid]
        prefix = "  " * depth + f"({pos[0]:>2},{pos[1]:>2}) "
        print(prefix + describe(e))

        # Branching:
        #   - Transports flow downstream by their facing / bridge-target.
        #   - Harvesters have no facing — fan out to adjacent consuming transports.
        #   - Foundries / cores terminate a chain.
        if args.upstream:
            if e["kind"] in ("conveyor", "splitter", "armoured_conveyor", "bridge", "foundry"):
                for feeder_id in _conveyor_inputs(pos, entities):
                    walk(entities[feeder_id]["pos"], depth + 1)
            return
        if e["kind"] == "harvester":
            for adj in _harvester_consumers(pos, entities, tile):
                walk(adj, depth + 1)
            return
        if e["kind"] in ("conveyor", "splitter", "armoured_conveyor", "bridge"):
            for nxt in _conveyor_outputs(e):
                walk(nxt, depth + 1)
            return
        # foundry / core / others: terminal node downstream.

    walk(start, 0)


# ---------------------------------------------------------------------------
# CLI plumbing

def _parse_region(raw: str) -> tuple[int, int, int, int]:
    parts = [int(x.strip()) for x in raw.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("region must be 'x1,y1,x2,y2'")
    return tuple(parts)  # type: ignore[return-value]


def _parse_turn_range(raw: str) -> tuple[int, int]:
    if "-" in raw:
        a, b = raw.split("-", 1)
        return int(a), int(b)
    return int(raw), int(raw)


def _parse_xy(raw: str) -> tuple[int, int]:
    parts = [int(x.strip()) for x in raw.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("expected 'x,y'")
    return parts[0], parts[1]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="replay_cli",
        description="Replay analysis CLI for Battlecode-26 Cambridge.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            examples:
              uv run scripts/replay_cli.py grid replay.replay26 --turn 64 --region 14,1,22,8
              uv run scripts/replay_cli.py trace replay.replay26 --bot 190 --turns 60-80
              uv run scripts/replay_cli.py flow replay.replay26 --turns 50-100 --region 14,1,22,8
              uv run scripts/replay_cli.py diff replay.replay26 --turn-a 63 --turn-b 70
              uv run scripts/replay_cli.py chain replay.replay26 --turn 64 --start 17,4
        """),
    )
    p.add_argument("--cache-rebuild", action="store_true",
                   help="ignore on-disk parse cache and reparse the replay")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("grid", help="region snapshot at a turn")
    g.add_argument("replay")
    g.add_argument("--turn", type=int, required=True)
    g.add_argument("--region", type=_parse_region, default=None,
                   help="x1,y1,x2,y2; default is a 12x12 window from origin or use --full")
    g.add_argument("--full", action="store_true", help="render the entire map (wide output)")

    t = sub.add_parser("trace", help="one bot's per-turn timeline")
    t.add_argument("replay")
    t.add_argument("--bot", type=int, required=True)
    t.add_argument("--turns", type=_parse_turn_range, required=True,
                   help="A-B inclusive (e.g. 60-80) or single turn N")
    t.add_argument("--full", action="store_true",
                   help="show raw stdout when no role-tagged log line is present")

    f = sub.add_parser("flow", help="resource flow per tile over a window")
    f.add_argument("replay")
    f.add_argument("--turns", type=_parse_turn_range, required=True)
    f.add_argument("--region", type=_parse_region, default=None)
    f.add_argument("--full", action="store_true", help="aggregate over the full map")
    f.add_argument("--edges", action="store_true",
                   help="also list the top src→dst edges")

    d = sub.add_parser("diff", help="event log between two turns")
    d.add_argument("replay")
    d.add_argument("--turn-a", type=int, required=True)
    d.add_argument("--turn-b", type=int, required=True)
    d.add_argument("--region", type=_parse_region, default=None,
                   help="if omitted, diffs across the whole map")
    d.add_argument("--kinds", nargs="+", default=None,
                   help="restrict to event kinds: place,remove,move,hp,fire,battack,ind_dot,ind_line")

    c = sub.add_parser("chain", help="follow a conveyor chain from a tile")
    c.add_argument("replay")
    c.add_argument("--turn", type=int, required=True)
    c.add_argument("--start", type=_parse_xy, required=True)
    c.add_argument("--upstream", action="store_true",
                   help="follow feeders backwards instead of outputs forward")
    c.add_argument("--depth", type=int, default=24,
                   help="maximum recursion depth (default 24)")

    args = p.parse_args(argv)
    if args.cache_rebuild:
        # Force reparse: easier to nuke the cache than thread a flag through.
        for f_path in CACHE_DIR.glob("*.pkl"):
            try:
                f_path.unlink()
            except OSError:
                pass
    replay = load_replay(args.replay)

    handler = {
        "grid":  cmd_grid,
        "trace": cmd_trace,
        "flow":  cmd_flow,
        "diff":  cmd_diff,
        "chain": cmd_chain,
    }[args.cmd]
    handler(replay, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
