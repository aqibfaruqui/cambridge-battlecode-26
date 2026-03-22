import type {
  GameEvent,
  GameEventType,
  ParsedEntity,
  ParsedReplay,
  RoundSnapshot,
  TeamId,
  TeamState,
  TileType,
} from "@/types/game";
import { CORE_FOOTPRINT, CORE_MAX_HP } from "@/lib/game-constants";

function isTeamId(v: unknown): v is TeamId {
  return v === "a" || v === "b";
}

function asPos(v: unknown): [number, number] | undefined {
  if (Array.isArray(v) && v.length >= 2 && typeof v[0] === "number" && typeof v[1] === "number") {
    return [v[0], v[1]];
  }
  if (v && typeof v === "object" && "x" in v && "y" in v) {
    const o = v as { x: unknown; y: unknown };
    if (typeof o.x === "number" && typeof o.y === "number") return [o.x, o.y];
  }
  return undefined;
}

function parseEntity(o: Record<string, unknown>, fallbackId: number): ParsedEntity | null {
  const type = typeof o.type === "string" ? o.type : typeof o.entity_type === "string" ? o.entity_type : null;
  if (!type) return null;
  const pos = asPos(o.position ?? o.pos ?? o.loc);
  if (!pos) return null;
  const teamRaw = o.team ?? o.side;
  if (!isTeamId(teamRaw)) return null;
  const idNum = typeof o.id === "number" ? o.id : fallbackId;
  const hp = typeof o.hp === "number" ? o.hp : typeof o.health === "number" ? o.health : 0;
  const ent: ParsedEntity = {
    id: idNum,
    type,
    position: pos,
    hp,
    team: teamRaw,
  };
  if (typeof o.direction === "string") ent.direction = o.direction;
  if (o.stored_resource === null || typeof o.stored_resource === "string") {
    ent.stored_resource = o.stored_resource as string | null;
  }
  if (typeof o.ammo === "number") ent.ammo = o.ammo;
  if (typeof o.footprint_w === "number") ent.footprint_w = o.footprint_w;
  if (typeof o.footprint_h === "number") ent.footprint_h = o.footprint_h;
  if (type === "core" && !ent.footprint_w) {
    ent.footprint_w = CORE_FOOTPRINT;
    ent.footprint_h = CORE_FOOTPRINT;
    if (ent.hp === 0) ent.hp = CORE_MAX_HP;
  }
  return ent;
}

function parseTeamState(o: unknown, label: string): TeamState | null {
  if (!o || typeof o !== "object") return null;
  const r = o as Record<string, unknown>;
  const titanium = typeof r.titanium === "number" ? r.titanium : typeof r.ti === "number" ? r.ti : 0;
  const axionite =
    typeof r.axionite === "number" ? r.axionite : typeof r.ax === "number" ? r.ax : 0;
  const scale_percent =
    typeof r.scale_percent === "number"
      ? r.scale_percent
      : typeof r.scale === "number"
        ? r.scale
        : 100;
  const rawEntities = r.entities ?? r.units ?? r.objects;
  const entities: ParsedEntity[] = [];
  if (Array.isArray(rawEntities)) {
    rawEntities.forEach((e, i) => {
      if (e && typeof e === "object") {
        const pe = parseEntity(e as Record<string, unknown>, i + 1);
        if (pe) entities.push(pe);
      }
    });
  }
  if (entities.length === 0 && process.env.NODE_ENV === "development") {
    console.warn(`[replay-parser] No entities parsed for ${label}`);
  }
  return { titanium, axionite, scale_percent, entities };
}

function parseGameEvent(o: Record<string, unknown>): GameEvent | null {
  const type = o.type as string;
  const valid: GameEventType[] = [
    "spawn",
    "move",
    "build",
    "destroy",
    "fire",
    "launch",
    "self_destruct",
    "heal",
    "resource_transfer",
    "damage",
  ];
  if (!valid.includes(type as GameEventType)) return null;
  const team = o.team;
  if (!isTeamId(team)) return null;
  const round =
    typeof o.round === "number"
      ? o.round
      : typeof o.turn === "number"
        ? o.turn
        : typeof o.round_number === "number"
          ? o.round_number
          : 0;
  const ev: GameEvent = { type: type as GameEventType, round, team };
  if (typeof o.entity_id === "number") ev.entity_id = o.entity_id;
  const p = asPos(o.position);
  if (p) ev.position = p;
  const t = asPos(o.target);
  if (t) ev.target = t;
  if (typeof o.building_type === "string") ev.building_type = o.building_type;
  if (typeof o.damage === "number") ev.damage = o.damage;
  if (typeof o.resource_type === "string") ev.resource_type = o.resource_type;
  return ev;
}

function parseMap(m: unknown): ParsedReplay["map"] | null {
  if (!m || typeof m !== "object") return null;
  const o = m as Record<string, unknown>;
  const width = typeof o.width === "number" ? o.width : null;
  const height = typeof o.height === "number" ? o.height : null;
  if (width === null || height === null) return null;
  const tilesRaw = o.tiles ?? o.grid ?? o.cells;
  const tiles: TileType[][] = [];
  if (Array.isArray(tilesRaw)) {
    for (let y = 0; y < height; y++) {
      const row = tilesRaw[y];
      const outRow: TileType[] = [];
      for (let x = 0; x < width; x++) {
        let cell: unknown;
        if (Array.isArray(row)) cell = row[x];
        else if (row && typeof row === "object") cell = (row as Record<string, unknown>)[String(x)];
        const s =
          typeof cell === "string"
            ? cell
            : cell && typeof cell === "object" && typeof (cell as { type?: string }).type === "string"
              ? (cell as { type: string }).type
              : "empty";
        const allowed: TileType[] = ["empty", "wall", "ore_titanium", "ore_axionite"];
        outRow.push(allowed.includes(s as TileType) ? (s as TileType) : "empty");
      }
      tiles.push(outRow);
    }
  } else {
    for (let y = 0; y < height; y++) {
      tiles.push(Array.from({ length: width }, () => "empty" as TileType));
    }
  }
  return { width, height, tiles };
}

function extractRounds(root: Record<string, unknown>): unknown[] | null {
  if (Array.isArray(root.rounds)) return root.rounds;
  if (Array.isArray(root.snapshots)) return root.snapshots;
  if (Array.isArray(root.frames)) return root.frames;
  if (Array.isArray(root.history)) return root.history;
  if (root.match && typeof root.match === "object") {
    const m = root.match as Record<string, unknown>;
    if (Array.isArray(m.rounds)) return m.rounds;
  }
  return null;
}

/**
 * Parse arbitrary replay JSON into ParsedReplay.
 * Logs unknown top-level keys in development.
 */
export function parseReplayJson(raw: unknown): ParsedReplay {
  if (raw === null || typeof raw !== "object") {
    throw new Error("Replay must be a JSON object");
  }
  const root = raw as Record<string, unknown>;

  if (process.env.NODE_ENV === "development") {
    const known = new Set([
      "map",
      "rounds",
      "winner",
      "win_reason",
      "snapshots",
      "frames",
      "history",
      "match",
    ]);
    for (const k of Object.keys(root)) {
      if (!known.has(k)) {
        console.info(`[replay-parser] Unknown top-level key: ${k}`);
      }
    }
  }

  const map =
    parseMap(root.map) ??
    (root.arena && typeof root.arena === "object" ? parseMap(root.arena) : null);
  if (!map) {
    throw new Error("Replay missing map { width, height, tiles }");
  }

  const roundsRaw = extractRounds(root);
  if (!roundsRaw) {
    throw new Error(
      "Replay missing rounds array (tried: rounds, snapshots, frames, history, match.rounds)",
    );
  }

  const rounds: RoundSnapshot[] = [];
  let ri = 0;
  for (const item of roundsRaw) {
    ri++;
    if (!item || typeof item !== "object") continue;
    const o = item as Record<string, unknown>;
    const round_number =
      typeof o.round_number === "number"
        ? o.round_number
        : typeof o.round === "number"
          ? o.round
          : typeof o.turn === "number"
            ? o.turn
            : typeof o.index === "number"
              ? o.index
              : ri;

    const team_a =
      parseTeamState(o.team_a ?? o.a ?? o.team1, "team_a") ??
      parseTeamState(o.red, "red");
    const team_b =
      parseTeamState(o.team_b ?? o.b ?? o.team2, "team_b") ??
      parseTeamState(o.blue, "blue");

    if (!team_a || !team_b) {
      console.warn(`[replay-parser] Skipping round ${round_number}: missing team states`);
      continue;
    }

    const events: GameEvent[] = [];
    const evRaw = o.events ?? o.log ?? o.actions;
    if (Array.isArray(evRaw)) {
      for (const e of evRaw) {
        if (e && typeof e === "object") {
          const ge = parseGameEvent(e as Record<string, unknown>);
          if (ge) events.push(ge);
        }
      }
    }

    rounds.push({
      round_number,
      team_a,
      team_b,
      events,
    });
  }

  if (rounds.length === 0) {
    throw new Error("No valid rounds parsed from replay");
  }

  const result = root.result;
  const winnerRaw =
    root.winner ??
    (result && typeof result === "object" && "winner" in result
      ? (result as { winner?: unknown }).winner
      : undefined);
  const winner: TeamId | null = winnerRaw === "a" || winnerRaw === "b" ? winnerRaw : null;
  const win_reason =
    typeof root.win_reason === "string"
      ? root.win_reason
      : typeof root.reason === "string"
        ? root.reason
        : "";

  return {
    map,
    rounds,
    winner,
    win_reason,
    raw,
  };
}
