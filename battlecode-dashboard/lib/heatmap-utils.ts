import type { ParsedReplay } from "@/types/game";

/** Count self-destruct blast tiles up to and including round index (0-based round list index). */
export function buildDeathHeatmap(
  replay: ParsedReplay,
  maxRoundIndex: number,
): number[][] {
  const { width, height } = replay.map;
  const grid = Array.from({ length: height }, () => Array.from({ length: width }, () => 0));
  for (let i = 0; i <= maxRoundIndex && i < replay.rounds.length; i++) {
    const r = replay.rounds[i];
    for (const ev of r.events) {
      if (ev.type !== "self_destruct") continue;
      const p = ev.target ?? ev.position;
      if (!p) continue;
      const [x, y] = p;
      if (y >= 0 && y < height && x >= 0 && x < width) grid[y][x]++;
    }
  }
  return grid;
}

/** Builder positions for last N rounds (by list index) for trail drawing. */
export function builderTrails(
  replay: ParsedReplay,
  endRoundIndex: number,
  trailLength: number,
): { team: "a" | "b"; points: [number, number][] }[] {
  const start = Math.max(0, endRoundIndex - trailLength + 1);
  const a: [number, number][] = [];
  const b: [number, number][] = [];
  for (let i = start; i <= endRoundIndex && i < replay.rounds.length; i++) {
    const r = replay.rounds[i];
    for (const e of r.team_a.entities) {
      if (e.type === "builder_bot") a.push([e.position[0], e.position[1]]);
    }
    for (const e of r.team_b.entities) {
      if (e.type === "builder_bot") b.push([e.position[0], e.position[1]]);
    }
  }
  return [
    { team: "a" as const, points: a },
    { team: "b" as const, points: b },
  ];
}
