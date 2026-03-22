"use client";

import type { MatchMetrics, ParsedReplay } from "@/types/game";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
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

export function CoreHpChart({ metrics, replay }: { metrics: MatchMetrics; replay: ParsedReplay }) {
  const data = useMemo(() => {
    const n = metrics.total_rounds;
    const out: { round: number; coreA: number; coreB: number }[] = [];
    for (let i = 0; i < n; i++) {
      out.push({
        round: replay.rounds[i]?.round_number ?? i + 1,
        coreA: metrics.core_a_hp_curve[i] ?? 0,
        coreB: metrics.core_b_hp_curve[i] ?? 0,
      });
    }
    return out;
  }, [metrics, replay.rounds]);

  return (
    <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
      <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wide text-[#8a8a9a]">
        Core HP over time
      </h3>
      <ResponsiveContainer width="100%" height={240}>
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
          />
          <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "#c8c8d8" }} />
          <Legend wrapperStyle={{ fontSize: 11, fontFamily: "var(--font-geist-mono)" }} />
          <Line type="monotone" dataKey="coreA" name="Core A HP" stroke="#4fc3f7" dot={false} strokeWidth={2} />
          <Line type="monotone" dataKey="coreB" name="Core B HP" stroke="#ff7043" dot={false} strokeWidth={2} />
          {metrics.first_blood_round && (
            <ReferenceLine
              x={metrics.first_blood_round}
              stroke="#ef5350"
              strokeDasharray="3 3"
              label={{ value: "First blood", fill: "#ef5350", fontSize: 9 }}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
      <div className="mt-2 flex gap-4 font-mono text-[10px] text-[#6a6a7a]">
        <span>Final A: {data[data.length - 1]?.coreA ?? "—"} HP</span>
        <span>Final B: {data[data.length - 1]?.coreB ?? "—"} HP</span>
        {metrics.first_blood_round && (
          <span>First blood: round {metrics.first_blood_round} ({metrics.first_blood_team})</span>
        )}
      </div>
    </div>
  );
}
