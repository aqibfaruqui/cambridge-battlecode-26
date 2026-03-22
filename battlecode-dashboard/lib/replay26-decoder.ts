/**
 * Decode a .replay26 binary (protobuf) file into our ParsedReplay format.
 *
 * The replay is event-sourced: an initial map + cores, then per-turn Update
 * deltas. We replay them to build per-round snapshots with entity lists and
 * resource totals, matching the shape the rest of the dashboard expects.
 */

import protobuf from "protobufjs";
import { REPLAY26_PROTO_JSON } from "./replay26-schema";
import type {
  GameEvent,
  ParsedEntity,
  ParsedReplay,
  RoundSnapshot,
  TeamId,
  TeamState,
  TileType,
} from "@/types/game";
import { CORE_FOOTPRINT, CORE_MAX_HP } from "./game-constants";

/* ---------- enum lookups ---------- */

const DIR_NAMES: Record<number, string> = {
  0: "centre",
  1: "north",
  2: "northeast",
  3: "east",
  4: "southeast",
  5: "south",
  6: "southwest",
  7: "west",
  8: "northwest",
};

const ENV_TILES: Record<number, TileType> = {
  0: "empty",
  1: "wall",
  2: "ore_titanium",
  3: "ore_axionite",
};

const RESOURCE_NAMES: Record<number, string> = {
  0: "none",
  1: "titanium",
  2: "raw_axionite",
  3: "refined_axionite",
};

function teamOf(v: number): TeamId {
  return v === 1 ? "b" : "a";
}

/* eslint-disable @typescript-eslint/no-explicit-any */

function entityKind(ent: any): string {
  if (ent.builderBot !== undefined && ent.builderBot !== null) return "builder_bot";
  if (ent.conveyor !== undefined && ent.conveyor !== null) return "conveyor";
  if (ent.splitter !== undefined && ent.splitter !== null) return "splitter";
  if (ent.armouredConveyor !== undefined && ent.armouredConveyor !== null) return "armoured_conveyor";
  if (ent.bridge !== undefined && ent.bridge !== null) return "bridge";
  if (ent.harvester !== undefined && ent.harvester !== null) return "harvester";
  if (ent.foundry !== undefined && ent.foundry !== null) return "foundry";
  if (ent.road !== undefined && ent.road !== null) return "road";
  if (ent.barrier !== undefined && ent.barrier !== null) return "barrier";
  if (ent.marker !== undefined && ent.marker !== null) return "marker";
  if (ent.core !== undefined && ent.core !== null) return "core";
  if (ent.gunner !== undefined && ent.gunner !== null) return "gunner";
  if (ent.sentinel !== undefined && ent.sentinel !== null) return "sentinel";
  if (ent.breach !== undefined && ent.breach !== null) return "breach";
  if (ent.launcher !== undefined && ent.launcher !== null) return "launcher";
  return "unknown";
}

function entityDirection(ent: any): string | undefined {
  const sub =
    ent.conveyor ??
    ent.splitter ??
    ent.armouredConveyor ??
    ent.gunner ??
    ent.sentinel ??
    ent.breach ??
    ent.launcher;
  if (sub && typeof sub.direction === "number") return DIR_NAMES[sub.direction];
  return undefined;
}

function entityStored(ent: any): string | null {
  const sub =
    ent.conveyor ?? ent.splitter ?? ent.armouredConveyor ?? ent.bridge ?? ent.foundry;
  if (sub && typeof sub.stored === "number" && sub.stored > 0)
    return RESOURCE_NAMES[sub.stored] ?? null;
  return null;
}

function entityAmmo(ent: any): number | undefined {
  const sub = ent.gunner ?? ent.sentinel ?? ent.breach ?? ent.launcher;
  if (sub && typeof sub.ammoAmount === "number") return sub.ammoAmount;
  return undefined;
}

function toParsedEntity(ent: any): ParsedEntity {
  const kind = entityKind(ent);
  const pe: ParsedEntity = {
    id: ent.id ?? 0,
    type: kind,
    position: [ent.position?.x ?? 0, ent.position?.y ?? 0],
    hp: ent.hp ?? 0,
    team: teamOf(ent.team ?? 0),
  };
  const dir = entityDirection(ent);
  if (dir) pe.direction = dir;
  const stored = entityStored(ent);
  if (stored && stored !== "none") pe.stored_resource = stored;
  const ammo = entityAmmo(ent);
  if (ammo !== undefined) pe.ammo = ammo;
  if (kind === "core") {
    pe.footprint_w = CORE_FOOTPRINT;
    pe.footprint_h = CORE_FOOTPRINT;
    if (pe.hp === 0) pe.hp = CORE_MAX_HP;
  }
  return pe;
}

/* ---------- state machine ---------- */

interface LiveEntity {
  raw: any;
  parsed: ParsedEntity;
}

interface SimState {
  entities: Map<number, LiveEntity>;
  tiA: number;
  axA: number;
  tiB: number;
  axB: number;
  tiCollectedA: number;
  tiCollectedB: number;
  axCollectedA: number;
  axCollectedB: number;
}

function snapshot(s: SimState, roundNum: number, events: GameEvent[]): RoundSnapshot {
  const teamEnts = (team: TeamId) => {
    const out: ParsedEntity[] = [];
    for (const le of s.entities.values()) {
      if (le.parsed.team === team) out.push({ ...le.parsed, position: [...le.parsed.position] as [number, number] });
    }
    return out;
  };
  const team_a: TeamState = {
    titanium: s.tiA,
    axionite: s.axA,
    scale_percent: 100, // we don't track scale in this decoder yet
    entities: teamEnts("a"),
  };
  const team_b: TeamState = {
    titanium: s.tiB,
    axionite: s.axB,
    scale_percent: 100,
    entities: teamEnts("b"),
  };
  return { round_number: roundNum, team_a, team_b, events };
}

function applyUpdates(state: SimState, updates: any[], roundNum: number): GameEvent[] {
  const events: GameEvent[] = [];

  for (const u of updates) {
    if (u.placeEntity) {
      const ent = u.placeEntity.entity;
      if (!ent) continue;
      const pe = toParsedEntity(ent);
      state.entities.set(pe.id, { raw: ent, parsed: pe });
      events.push({
        type: pe.type === "builder_bot" ? "spawn" : "build",
        round: roundNum,
        team: pe.team,
        entity_id: pe.id,
        position: [...pe.position] as [number, number],
        building_type: pe.type,
      });
    } else if (u.moveBuilderBot) {
      const le = state.entities.get(u.moveBuilderBot.id);
      if (le) {
        const oldPos: [number, number] = [...le.parsed.position] as [number, number];
        le.parsed.position = [u.moveBuilderBot.to?.x ?? 0, u.moveBuilderBot.to?.y ?? 0];
        events.push({
          type: "move",
          round: roundNum,
          team: le.parsed.team,
          entity_id: le.parsed.id,
          position: oldPos,
          target: [...le.parsed.position] as [number, number],
        });
      }
    } else if (u.removeEntity) {
      const le = state.entities.get(u.removeEntity.id);
      if (le) {
        const wasSelfDestruct = le.parsed.type === "builder_bot";
        events.push({
          type: wasSelfDestruct ? "self_destruct" : "destroy",
          round: roundNum,
          team: le.parsed.team,
          entity_id: le.parsed.id,
          position: [...le.parsed.position] as [number, number],
          target: [...le.parsed.position] as [number, number],
          damage: wasSelfDestruct ? 20 : undefined,
        });
        state.entities.delete(u.removeEntity.id);
      }
    } else if (u.updateHp) {
      const le = state.entities.get(u.updateHp.id);
      if (le) {
        le.parsed.hp += u.updateHp.delta ?? 0;
        const evType = (u.updateHp.delta ?? 0) > 0 ? "heal" : "damage";
        events.push({
          type: evType as GameEvent["type"],
          round: roundNum,
          team: le.parsed.team,
          entity_id: le.parsed.id,
          target: [...le.parsed.position] as [number, number],
          damage: evType === "damage" ? Math.abs(u.updateHp.delta ?? 0) : undefined,
        });
      }
    } else if (u.updatePlayers) {
      const p = u.updatePlayers.players;
      if (p?.a) {
        state.tiA = p.a.titanium ?? state.tiA;
        state.axA = p.a.axionite ?? state.axA;
        state.tiCollectedA = p.a.titaniumCollected ?? state.tiCollectedA;
        state.axCollectedA = p.a.axioniteCollected ?? state.axCollectedA;
      }
      if (p?.b) {
        state.tiB = p.b.titanium ?? state.tiB;
        state.axB = p.b.axionite ?? state.axB;
        state.tiCollectedB = p.b.titaniumCollected ?? state.tiCollectedB;
        state.axCollectedB = p.b.axioniteCollected ?? state.axCollectedB;
      }
    } else if (u.distributeResources) {
      for (const mv of u.distributeResources.moves ?? []) {
        if (mv.from && mv.to) {
          events.push({
            type: "resource_transfer",
            round: roundNum,
            team: "a",
            position: [mv.from.x ?? 0, mv.from.y ?? 0],
            target: [mv.to.x ?? 0, mv.to.y ?? 0],
          });
        }
      }
    } else if (u.fireTurret) {
      const from: [number, number] = [u.fireTurret.from?.x ?? 0, u.fireTurret.from?.y ?? 0];
      const to: [number, number] = [u.fireTurret.to?.x ?? 0, u.fireTurret.to?.y ?? 0];
      const shooter = [...state.entities.values()].find(
        (le) => le.parsed.position[0] === from[0] && le.parsed.position[1] === from[1],
      );
      events.push({
        type: "fire",
        round: roundNum,
        team: shooter?.parsed.team ?? "a",
        entity_id: shooter?.parsed.id,
        position: from,
        target: to,
      });
    }
  }
  return events;
}

/* ---------- public decoder ---------- */

let replayType: protobuf.Type | null = null;

function getReplayType(): protobuf.Type {
  if (!replayType) {
    replayType = protobuf.Root.fromJSON(REPLAY26_PROTO_JSON as protobuf.INamespace).lookupType(
      "battlecode.Replay",
    );
  }
  return replayType;
}

export function decodeReplay26(buffer: ArrayBuffer): ParsedReplay {
  const type = getReplayType();
  const msg = type.decode(new Uint8Array(buffer)) as any;

  const mapMsg = msg.map;
  const width: number = mapMsg?.width ?? 0;
  const height: number = mapMsg?.height ?? 0;

  const tiles: TileType[][] = [];
  for (let y = 0; y < height; y++) {
    const row: TileType[] = [];
    const tileRow = mapMsg?.rows?.[y];
    for (let x = 0; x < width; x++) {
      const env: number = tileRow?.tiles?.[x] ?? 0;
      row.push(ENV_TILES[env] ?? "empty");
    }
    tiles.push(row);
  }

  const state: SimState = {
    entities: new Map(),
    tiA: 1000,
    axA: 0,
    tiB: 1000,
    axB: 0,
    tiCollectedA: 0,
    tiCollectedB: 0,
    axCollectedA: 0,
    axCollectedB: 0,
  };

  for (const cp of mapMsg?.cores ?? []) {
    const pe: ParsedEntity = {
      id: cp.id ?? 0,
      type: "core",
      position: [cp.position?.x ?? 0, cp.position?.y ?? 0],
      hp: CORE_MAX_HP,
      team: teamOf(cp.team ?? 0),
      footprint_w: CORE_FOOTPRINT,
      footprint_h: CORE_FOOTPRINT,
    };
    state.entities.set(pe.id, { raw: cp, parsed: pe });
  }

  const rounds: RoundSnapshot[] = [];
  rounds.push(snapshot(state, 0, []));

  const rawTurns: any[] = msg.turns ?? [];
  for (let i = 0; i < rawTurns.length; i++) {
    const updates = rawTurns[i].updates ?? [];
    const events = applyUpdates(state, updates, i + 1);
    rounds.push(snapshot(state, i + 1, events));
  }

  const winner: TeamId | null =
    msg.winner === 0 ? "a" : msg.winner === 1 ? "b" : null;
  const win_reason =
    winner === "a"
      ? "Team A wins"
      : winner === "b"
        ? "Team B wins"
        : "Unknown outcome";

  return {
    map: { width, height, tiles },
    rounds,
    winner,
    win_reason,
    raw: { _format: "replay26", width, height, totalTurns: rawTurns.length, winner },
  };
}
/* eslint-enable @typescript-eslint/no-explicit-any */
