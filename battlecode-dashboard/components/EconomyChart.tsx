"use client";

import type { MatchMetrics, ParsedReplay, TeamId } from "@/types/game";
import {
  Bar,
  BarChart,
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

const axis = { stroke: "#4a4a5a", fontSize: 10, fontFamily: "var(--font-geist-mono)" };
const grid = { stroke: "#2a2a38" };

export function EconomyChart({ metrics, replay }: { metrics: MatchMetrics; replay: ParsedReplay }) {
  const lineData = useMemo(() => {
    const n = metrics.total_rounds;
    const out: Record<string, number | string>[] = [];
    for (let i = 0; i < n; i++) {
      const ra = replay.rounds[i];
      out.push({
        round: ra?.round_number ?? i + 1,
        tiA: metrics.teams.a.titanium_curve[i] ?? 0,
        tiB: metrics.teams.b.titanium_curve[i] ?? 0,
        axA: metrics.teams.a.axionite_curve[i] ?? 0,
        axB: metrics.teams.b.axionite_curve[i] ?? 0,
        scA: metrics.teams.a.scale_curve[i] ?? 0,
        scB: metrics.teams.b.scale_curve[i] ?? 0,
      });
    }
    return out;
  }, [metrics, replay.rounds]);

  const spendData = useMemo(() => {
    const tally = (team: TeamId) => {
      const m: Record<string, number> = {};
      const b = team === "a" ? metrics.teams.a.buildings_built : metrics.teams.b.buildings_built;
      for (const x of b) {
        m[x.type] = (m[x.type] ?? 0) + 1;
      }
      return m;
    };
    const a = tally("a");
    const b = tally("b");
    const types = Array.from(new Set([...Object.keys(a), ...Object.keys(b)])).sort();
    return types.map((t) => ({ type: t, a: a[t] ?? 0, b: b[t] ?? 0 }));
  }, [metrics]);

  const annA = metrics.teams.a;
  const annB = metrics.teams.b;

  return (
    <div className="flex flex-col gap-6">
      <ChartBlock title="Titanium (stock)">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={lineData}>
            <CartesianGrid {...grid} />
            <XAxis dataKey="round" {...axis} tick={{ fill: "#8a8a9a" }} />
            <YAxis {...axis} tick={{ fill: "#8a8a9a" }} />
            <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: "#c8c8d8" }} />
            <Legend wrapperStyle={{ fontSize: 11, fontFamily: "var(--font-geist-mono)" }} />
            <Line type="monotone" dataKey="tiA" name="A Ti" stroke="#4fc3f7" dot={false} strokeWidth={1.5} />
            <Line type="monotone" dataKey="tiB" name="B Ti" stroke="#ff7043" dot={false} strokeWidth={1.5} />
            {annA.first_harvester_round && (
              <ReferenceLine
                x={annA.first_harvester_round}
                stroke="#4fc3f7"
                strokeDasharray="3 3"
                label={{ value: "A 1st harv", fill: "#4fc3f7", fontSize: 9 }}
              />
            )}
            {annB.first_harvester_round && (
              <ReferenceLine
                x={annB.first_harvester_round}
                stroke="#ff7043"
                strokeDasharray="3 3"
                label={{ value: "B 1st harv", fill: "#ff7043", fontSize: 9 }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </ChartBlock>

      <ChartBlock title="Axionite (stock)">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={lineData}>
            <CartesianGrid {...grid} />
            <XAxis dataKey="round" {...axis} tick={{ fill: "#8a8a9a" }} />
            <YAxis {...axis} tick={{ fill: "#8a8a9a" }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 11, fontFamily: "var(--font-geist-mono)" }} />
            <Line type="monotone" dataKey="axA" name="A Ax" stroke="#4fc3f7" dot={false} strokeWidth={1.5} />
            <Line type="monotone" dataKey="axB" name="B Ax" stroke="#ff7043" dot={false} strokeWidth={1.5} />
            {annA.first_foundry_round && (
              <ReferenceLine
                x={annA.first_foundry_round}
                stroke="#4fc3f7"
                strokeDasharray="3 3"
                label={{ value: "A 1st foundry", fill: "#4fc3f7", fontSize: 9 }}
              />
            )}
            {annB.first_foundry_round && (
              <ReferenceLine
                x={annB.first_foundry_round}
                stroke="#ff7043"
                strokeDasharray="3 3"
                label={{ value: "B 1st foundry", fill: "#ff7043", fontSize: 9 }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </ChartBlock>

      <ChartBlock title="Scale %">
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={lineData}>
            <CartesianGrid {...grid} />
            <XAxis dataKey="round" {...axis} tick={{ fill: "#8a8a9a" }} />
            <YAxis {...axis} tick={{ fill: "#8a8a9a" }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 11, fontFamily: "var(--font-geist-mono)" }} />
            <Line type="monotone" dataKey="scA" name="A scale" stroke="#4fc3f7" dot={false} strokeWidth={1.5} />
            <Line type="monotone" dataKey="scB" name="B scale" stroke="#ff7043" dot={false} strokeWidth={1.5} />
            <ReferenceLine y={300} stroke="#888" strokeDasharray="4 4" label={{ value: "300%", fontSize: 9 }} />
          </LineChart>
        </ResponsiveContainer>
      </ChartBlock>

      <ChartBlock title="Build counts by type (cumulative placements)">
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={spendData} layout="vertical" margin={{ left: 72 }}>
            <CartesianGrid {...grid} horizontal={false} />
            <XAxis type="number" {...axis} tick={{ fill: "#8a8a9a" }} />
            <YAxis type="category" dataKey="type" width={68} {...axis} tick={{ fill: "#8a8a9a" }} />
            <Tooltip contentStyle={tooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 11, fontFamily: "var(--font-geist-mono)" }} />
            <Bar dataKey="a" name="Team A" fill="#4fc3f7" />
            <Bar dataKey="b" name="Team B" fill="#ff7043" />
          </BarChart>
        </ResponsiveContainer>
      </ChartBlock>
    </div>
  );
}

function ChartBlock({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
      <h3 className="mb-2 font-mono text-[11px] uppercase tracking-wide text-[#8a8a9a]">{title}</h3>
      {children}
    </div>
  );
}

const tooltipStyle = {
  backgroundColor: "#1a1a24",
  border: "1px solid #2a2a38",
  fontSize: 11,
  fontFamily: "var(--font-geist-mono)",
};
