"use client";

import type { ParsedReplay } from "@/types/game";
import { buildDeathHeatmap, builderTrails } from "@/lib/heatmap-utils";

export function computeHeatmapOverlay(
  replay: ParsedReplay,
  roundIndex: number,
  trailRounds: number,
): { death: number[][]; trailsA: [number, number][]; trailsB: [number, number][] } {
  const trails = builderTrails(replay, roundIndex, trailRounds);
  return {
    death: buildDeathHeatmap(replay, roundIndex),
    trailsA: trails.find((x) => x.team === "a")!.points,
    trailsB: trails.find((x) => x.team === "b")!.points,
  };
}
