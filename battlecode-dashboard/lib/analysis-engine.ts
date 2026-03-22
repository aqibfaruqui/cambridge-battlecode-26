import type { GameEvent, MatchMetrics, ParsedEntity, ParsedReplay, TeamId } from "@/types/game";
import {
  BASE_AXIONITE_COST,
  BASE_TITANIUM_COST,
  BUILDER_BOT_SELF_DESTRUCT_DAMAGE,
  CORE_FOOTPRINT,
  TURRET_TYPES,
} from "@/lib/game-constants";

function coreAnchorTiles(core: ParsedEntity): [number, number][] {
  const w = core.footprint_w ?? CORE_FOOTPRINT;
  const h = core.footprint_h ?? CORE_FOOTPRINT;
  const [x, y] = core.position;
  const out: [number, number][] = [];
  for (let dy = 0; dy < h; dy++) {
    for (let dx = 0; dx < w; dx++) {
      out.push([x + dx, y + dy]);
    }
  }
  return out;
}

function tileSet(tiles: [number, number][]): Set<string> {
  return new Set(tiles.map(([x, y]) => `${x},${y}`));
}

function getCore(state: { entities: ParsedEntity[] }, team: TeamId): ParsedEntity | undefined {
  return state.entities.find((e) => e.type === "core" && e.team === team);
}

function collectAllEvents(rounds: ParsedReplay["rounds"]): GameEvent[] {
  const out: GameEvent[] = [];
  for (const r of rounds) {
    out.push(...r.events);
  }
  return out;
}

const CONVEYOR_LIKE = new Set([
  "conveyor",
  "armoured_conveyor",
  "splitter",
  "bridge",
]);

function directionDelta(dir: string | undefined): [number, number] | null {
  if (!dir) return null;
  const d = dir.toLowerCase();
  const map: Record<string, [number, number]> = {
    north: [0, -1],
    northeast: [1, -1],
    east: [1, 0],
    southeast: [1, 1],
    south: [0, 1],
    southwest: [-1, 1],
    west: [-1, 0],
    northwest: [-1, -1],
  };
  return map[d] ?? null;
}

/** Heuristic: harvester has conveyor-like neighbor pointing toward a tile closer to friendly core */
function harvesterConnected(
  h: ParsedEntity,
  entities: ParsedEntity[],
  corePos: [number, number],
): boolean {
  const [hx, hy] = h.position;
  const [cx, cy] = corePos;
  for (const e of entities) {
    if (!CONVEYOR_LIKE.has(e.type)) continue;
    const [ex, ey] = e.position;
    if (Math.abs(ex - hx) + Math.abs(ey - hy) !== 1) continue;
    const delta = directionDelta(e.direction);
    if (!delta) continue;
    const outX = ex + delta[0];
    const outY = ey + delta[1];
    const distBefore = (hx - cx) ** 2 + (hy - cy) ** 2;
    const distAfter = (outX - cx) ** 2 + (outY - cy) ** 2;
    if (distAfter < distBefore) return true;
  }
  return false;
}

function analyzeTeam(
  replay: ParsedReplay,
  team: TeamId,
  allEvents: GameEvent[],
): MatchMetrics["teams"][string] {
  const other: TeamId = team === "a" ? "b" : "a";
  const rounds = replay.rounds;

  const titanium_curve: number[] = [];
  const axionite_curve: number[] = [];
  const scale_curve: number[] = [];
  const avg_builder_distance_from_core: number[] = [];

  const heatW = replay.map.width;
  const heatH = replay.map.height;
  const builder_positions_heatmap: number[][] = Array.from({ length: heatH }, () =>
    Array.from({ length: heatW }, () => 0),
  );

  let peak_titanium = 0;
  let peak_axionite = 0;
  let peak_builder_count = 0;
  let total_builders_spawned = 0;

  function enemyCoreTilesAtRound(roundNum: number): Set<string> {
    const snap = rounds.find((rr) => rr.round_number === roundNum) ?? rounds[roundNum - 1];
    if (!snap) return new Set();
    const st = team === "a" ? snap.team_b : snap.team_a;
    const core = getCore(st, other);
    return core ? tileSet(coreAnchorTiles(core)) : new Set();
  }

  let total_self_destructs = 0;
  let core_hits = 0;

  for (const r of rounds) {
    const st = team === "a" ? r.team_a : r.team_b;
    titanium_curve.push(st.titanium);
    axionite_curve.push(st.axionite);
    scale_curve.push(st.scale_percent);
    peak_titanium = Math.max(peak_titanium, st.titanium);
    peak_axionite = Math.max(peak_axionite, st.axionite);

    const core = getCore(st, team);
    const builders = st.entities.filter((e) => e.type === "builder_bot");
    peak_builder_count = Math.max(peak_builder_count, builders.length);

    if (core) {
      const [cx, cy] = core.position;
      const anchor = [cx + (core.footprint_w ?? CORE_FOOTPRINT) / 2, cy + (core.footprint_h ?? CORE_FOOTPRINT) / 2];
      let sum = 0;
      let n = 0;
      for (const b of builders) {
        const [bx, by] = b.position;
        sum += Math.hypot(bx - anchor[0], by - anchor[1]);
        n++;
        if (by >= 0 && by < heatH && bx >= 0 && bx < heatW) {
          builder_positions_heatmap[by][bx]++;
        }
      }
      avg_builder_distance_from_core.push(n ? sum / n : 0);
    } else {
      avg_builder_distance_from_core.push(0);
    }
  }

  for (const ev of allEvents) {
    if (ev.team !== team) continue;
    if (ev.type === "spawn") total_builders_spawned++;
    if (ev.type === "self_destruct") {
      total_self_destructs++;
      const pos = ev.target ?? ev.position;
      if (pos && enemyCoreTilesAtRound(ev.round).has(`${pos[0]},${pos[1]}`)) {
        core_hits++;
      }
    }
  }

  const buildings_built: { type: string; round: number; position: [number, number] }[] = [];
  let total_titanium_spent = 0;
  let total_axionite_spent = 0;

  for (const ev of allEvents) {
    if (ev.team !== team || ev.type !== "build") continue;
    const bt = ev.building_type ?? "unknown";
    const pos = ev.position ?? [0, 0];
    buildings_built.push({ type: bt, round: ev.round, position: pos });
    total_titanium_spent += BASE_TITANIUM_COST[bt] ?? 0;
    total_axionite_spent += BASE_AXIONITE_COST[bt] ?? 0;
  }

  const firstOf = (t: string) => {
    const b = buildings_built.filter((x) => x.type === t);
    if (!b.length) return null;
    return Math.min(...b.map((x) => x.round));
  };

  const total_harvesters_built = buildings_built.filter((b) => b.type === "harvester").length;
  const total_gunners_built = buildings_built.filter((b) => b.type === "gunner").length;
  const total_conveyors_built = buildings_built.filter((b) => b.type === "conveyor").length;
  const total_roads_built = buildings_built.filter((b) => b.type === "road").length;
  const total_barriers_built = buildings_built.filter((b) => b.type === "barrier").length;

  const firedIds = new Set<number>();
  let turret_damage_dealt = 0;
  for (const ev of allEvents) {
    if (ev.team === team && ev.type === "fire" && typeof ev.entity_id === "number") {
      firedIds.add(ev.entity_id);
    }
    if (ev.team === team && ev.type === "fire" && typeof ev.damage === "number") {
      turret_damage_dealt += ev.damage;
    }
  }

  const lastState = team === "a" ? rounds[rounds.length - 1].team_a : rounds[rounds.length - 1].team_b;
  const core = getCore(lastState, team);
  const corePos: [number, number] = core
    ? [core.position[0] + (core.footprint_w ?? CORE_FOOTPRINT) / 2, core.position[1] + (core.footprint_h ?? CORE_FOOTPRINT) / 2]
    : [0, 0];

  const harvesters = lastState.entities.filter((e) => e.type === "harvester");
  let harvesters_with_connected_chain = 0;
  let harvesters_without_chain = 0;
  for (const h of harvesters) {
    if (harvesterConnected(h, lastState.entities, corePos)) harvesters_with_connected_chain++;
    else harvesters_without_chain++;
  }

  const turretIdsEver = new Set<number>();
  for (const r of rounds) {
    const st = team === "a" ? r.team_a : r.team_b;
    for (const e of st.entities) {
      if (TURRET_TYPES.has(e.type)) turretIdsEver.add(e.id);
    }
  }
  let turrets_that_fired = 0;
  let turrets_that_never_fired = 0;
  for (const tid of turretIdsEver) {
    if (firedIds.has(tid)) turrets_that_fired++;
    else turrets_that_never_fired++;
  }

  const turret_shots_fired = allEvents.filter((e) => e.team === team && e.type === "fire").length;

  const final = rounds[rounds.length - 1];
  const fs = team === "a" ? final.team_a : final.team_b;

  return {
    titanium_curve,
    axionite_curve,
    scale_curve,
    total_titanium_spent,
    total_axionite_spent,
    peak_titanium,
    peak_axionite,
    final_scale: fs.scale_percent,
    buildings_built,
    first_harvester_round: firstOf("harvester"),
    first_gunner_round: firstOf("gunner"),
    first_launcher_round: firstOf("launcher"),
    first_foundry_round: firstOf("foundry"),
    total_harvesters_built,
    total_gunners_built,
    total_conveyors_built,
    total_roads_built,
    total_barriers_built,
    total_builders_spawned,
    peak_builder_count,
    builder_spawn_rate: (total_builders_spawned / Math.max(1, rounds.length)) * 50,
    total_self_destructs,
    core_hits,
    core_damage_dealt: core_hits * BUILDER_BOT_SELF_DESTRUCT_DAMAGE,
    turret_shots_fired,
    turret_damage_dealt,
    self_destruct_efficiency:
      total_self_destructs > 0 ? core_hits / total_self_destructs : 0,
    avg_builder_distance_from_core,
    builder_positions_heatmap,
    harvesters_with_connected_chain,
    harvesters_without_chain,
    turrets_that_fired,
    turrets_that_never_fired,
  };
}

export function computeMatchMetrics(replay: ParsedReplay): MatchMetrics {
  const rounds = replay.rounds;
  const allEvents = collectAllEvents(rounds);

  const core_a_hp_curve = rounds.map(
    (r) => r.team_a.entities.find((e) => e.type === "core")?.hp ?? 0,
  );
  const core_b_hp_curve = rounds.map(
    (r) => r.team_b.entities.find((e) => e.type === "core")?.hp ?? 0,
  );

  let first_blood_round: number | null = null;
  let first_blood_team: string | null = null;

  const coreATiles = (r: (typeof rounds)[0]) => {
    const c = getCore(r.team_a, "a");
    return c ? tileSet(coreAnchorTiles(c)) : new Set<string>();
  };
  const coreBTiles = (r: (typeof rounds)[0]) => {
    const c = getCore(r.team_b, "b");
    return c ? tileSet(coreAnchorTiles(c)) : new Set<string>();
  };

  const sortedCombat = [...allEvents].sort((a, b) => a.round - b.round);
  for (const ev of sortedCombat) {
    if (ev.type !== "damage" && ev.type !== "self_destruct") continue;
    const pos = ev.target ?? ev.position;
    if (!pos) continue;
    const key = `${pos[0]},${pos[1]}`;
    const snap = rounds.find((rr) => rr.round_number === ev.round) ?? rounds[ev.round - 1];
    if (!snap) continue;
    const hitA = coreATiles(snap).has(key);
    const hitB = coreBTiles(snap).has(key);
    if (hitA || hitB) {
      first_blood_round = ev.round;
      if (hitA && hitB) first_blood_team = "both";
      else if (hitA) first_blood_team = "a_victim";
      else first_blood_team = "b_victim";
      break;
    }
  }

  return {
    winner: replay.winner,
    win_reason: replay.win_reason,
    total_rounds: rounds.length,
    map_size: [replay.map.width, replay.map.height],
    teams: {
      a: analyzeTeam(replay, "a", allEvents),
      b: analyzeTeam(replay, "b", allEvents),
    },
    core_a_hp_curve,
    core_b_hp_curve,
    first_blood_round,
    first_blood_team,
  };
}
