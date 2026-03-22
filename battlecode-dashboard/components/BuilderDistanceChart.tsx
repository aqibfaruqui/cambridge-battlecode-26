"use client";

import type { MatchMetrics, ParsedReplay } from "@/types/game";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMemo } from "react";

const tooltipStyle = {
  backgroundColor: "#1a1a24",
  border: "1px solid #2a2a38",
  fontSize: 11,
  fontFamily: "var(--font-geist-mono)",
};

export function BuilderDistanceChart({ metrics, replay }: { metrics: MatchMetrics; replay: ParsedReplay }) {
  const data = useMemo(() => {
    const n = metrics.total_rounds;
    const out: { round: number; distA: number; distB: number }[] = [];
    for (let i = 0; i < n; i++) {
      out.push({
        round: replay.rounds[i]?.round_number ?? i + 1,
        distA: +(metrics.teams.a.avg_builder_distance_from_core[i] ?? 0).toFixed(2),
        distB: +(metrics.teams.b.avg_builder_distance_from_core[i] ?? 0).toFixed(2),
      });
    }
    return out;
  }, [metrics, replay.rounds]);

  return (
    <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
      <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wide text-[#8a8a9a]">
        Avg builder distance from core
      </h3>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data}>
          <CartesianGrid stroke="#2a2a38" />
          <XAxis
            dataKey="round"
            stroke="#4a4a5a"
            fontSize={10}
            fontFamily="var(--font-geist-mono)"
            tick={{ fill: "#8a8a9a" }}
          />
          <YAxis
            stroke="#4a4a5a"
            fontSize={10}
            fontFamily="var(--font-geist-mono)"
            tick={{ fill: "#8a8a9a" }}
            label={{ value: "tiles", angle: -90, position: "insideLeft", fill: "#6a6a7a", fontSize: 9 }}
          />
          <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "#c8c8d8" }} />
          <Legend wrapperStyle={{ fontSize: 11, fontFamily: "var(--font-geist-mono)" }} />
          <Line type="monotone" dataKey="distA" name="A avg dist" stroke="#4fc3f7" dot={false} strokeWidth={1.5} />
          <Line type="monotone" dataKey="distB" name="B avg dist" stroke="#ff7043" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
      <p className="mt-1 font-mono text-[10px] text-[#6a6a7a]">
        Higher distance = more aggressive expansion; lower = turtling near base.
      </p>
    </div>
  );
}
