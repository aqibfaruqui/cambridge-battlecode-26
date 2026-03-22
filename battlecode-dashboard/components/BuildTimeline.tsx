"use client";

import type { MatchMetrics } from "@/types/game";
import { useMemo } from "react";

const TYPE_COLORS: Record<string, string> = {
  harvester: "#66bb6a",
  conveyor: "#78909c",
  armoured_conveyor: "#5c6bc0",
  splitter: "#ab47bc",
  bridge: "#8d6e63",
  foundry: "#ffa726",
  gunner: "#ef5350",
  sentinel: "#42a5f5",
  breach: "#ff7043",
  launcher: "#ec407a",
  road: "#9e9e9e",
  barrier: "#795548",
  marker: "#bdbdbd",
};

interface Event {
  type: string;
  round: number;
  team: "a" | "b";
}

export function BuildTimeline({ metrics }: { metrics: MatchMetrics }) {
  const events = useMemo(() => {
    const out: Event[] = [];
    for (const b of metrics.teams.a.buildings_built) {
      out.push({ type: b.type, round: b.round, team: "a" });
    }
    for (const b of metrics.teams.b.buildings_built) {
      out.push({ type: b.type, round: b.round, team: "b" });
    }
    out.sort((a, b) => a.round - b.round);
    return out;
  }, [metrics]);

  const maxRound = metrics.total_rounds;
  const types = useMemo(() => {
    const s = new Set<string>();
    for (const e of events) s.add(e.type);
    return Array.from(s).sort();
  }, [events]);

  const milestones = useMemo(() => {
    const m: { label: string; round: number; color: string }[] = [];
    const add = (label: string, round: number | null, color: string) => {
      if (round) m.push({ label, round, color });
    };
    add("A 1st harv", metrics.teams.a.first_harvester_round, "#4fc3f7");
    add("B 1st harv", metrics.teams.b.first_harvester_round, "#ff7043");
    add("A 1st gun", metrics.teams.a.first_gunner_round, "#4fc3f7");
    add("B 1st gun", metrics.teams.b.first_gunner_round, "#ff7043");
    add("A 1st launch", metrics.teams.a.first_launcher_round, "#4fc3f7");
    add("B 1st launch", metrics.teams.b.first_launcher_round, "#ff7043");
    if (metrics.first_blood_round) m.push({ label: "1st blood", round: metrics.first_blood_round, color: "#ef5350" });
    return m.sort((a, b) => a.round - b.round);
  }, [metrics]);

  const rowH = 28;
  const headerH = 24;
  const chartH = headerH + types.length * rowH * 2 + rowH;
  const leftW = 100;

  return (
    <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
      <h3 className="mb-3 font-mono text-[11px] uppercase tracking-wide text-[#8a8a9a]">
        Build timeline
      </h3>

      {/* Legend */}
      <div className="mb-3 flex flex-wrap gap-3">
        {types.map((t) => (
          <span key={t} className="flex items-center gap-1 font-mono text-[10px] text-[#a8a8b8]">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: TYPE_COLORS[t] ?? "#888" }}
            />
            {t}
          </span>
        ))}
      </div>

      <div className="overflow-x-auto">
        <svg width="100%" viewBox={`0 0 900 ${chartH}`} className="min-w-[600px]">
          {/* Round axis */}
          {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
            const r = Math.round(frac * maxRound);
            const x = leftW + frac * (900 - leftW - 10);
            return (
              <g key={frac}>
                <line x1={x} y1={headerH} x2={x} y2={chartH} stroke="#2a2a38" strokeWidth={1} />
                <text x={x} y={14} fill="#6a6a7a" fontSize={9} textAnchor="middle" fontFamily="var(--font-geist-mono)">
                  R{r}
                </text>
              </g>
            );
          })}

          {/* Milestone lines */}
          {milestones.map((m, i) => {
            const x = leftW + (m.round / maxRound) * (900 - leftW - 10);
            return (
              <g key={i}>
                <line x1={x} y1={headerH} x2={x} y2={chartH} stroke={m.color} strokeWidth={1} strokeDasharray="3 3" opacity={0.5} />
                <text x={x + 2} y={chartH - 4} fill={m.color} fontSize={8} fontFamily="var(--font-geist-mono)">
                  {m.label}
                </text>
              </g>
            );
          })}

          {/* Rows: two rows per type (Team A and Team B) */}
          {types.map((type, ti) => {
            const yA = headerH + ti * rowH * 2;
            const yB = yA + rowH;
            const typeEvents = events.filter((e) => e.type === type);
            const evA = typeEvents.filter((e) => e.team === "a");
            const evB = typeEvents.filter((e) => e.team === "b");

            return (
              <g key={type}>
                {/* Row backgrounds */}
                <rect x={0} y={yA} width={900} height={rowH} fill={ti % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent"} />
                <rect x={0} y={yB} width={900} height={rowH} fill={ti % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent"} />

                {/* Labels */}
                <text x={4} y={yA + rowH / 2 + 3} fill="#4fc3f7" fontSize={9} fontFamily="var(--font-geist-mono)">
                  A {type}
                </text>
                <text x={4} y={yB + rowH / 2 + 3} fill="#ff7043" fontSize={9} fontFamily="var(--font-geist-mono)">
                  B {type}
                </text>

                {/* Event dots */}
                {evA.map((e, i) => {
                  const x = leftW + (e.round / maxRound) * (900 - leftW - 10);
                  return (
                    <circle
                      key={`a-${i}`}
                      cx={x}
                      cy={yA + rowH / 2}
                      r={3.5}
                      fill={TYPE_COLORS[type] ?? "#888"}
                      opacity={0.85}
                    >
                      <title>A built {type} at round {e.round}</title>
                    </circle>
                  );
                })}
                {evB.map((e, i) => {
                  const x = leftW + (e.round / maxRound) * (900 - leftW - 10);
                  return (
                    <circle
                      key={`b-${i}`}
                      cx={x}
                      cy={yB + rowH / 2}
                      r={3.5}
                      fill={TYPE_COLORS[type] ?? "#888"}
                      opacity={0.85}
                    >
                      <title>B built {type} at round {e.round}</title>
                    </circle>
                  );
                })}

                {/* Separator line */}
                <line x1={leftW} y1={yB + rowH} x2={900} y2={yB + rowH} stroke="#1a1a24" strokeWidth={0.5} />
              </g>
            );
          })}
        </svg>
      </div>

      {/* Summary stats */}
      <div className="mt-3 grid grid-cols-2 gap-4 font-mono text-[10px] text-[#8a8a9a]">
        <div>
          <span className="text-[#4fc3f7]">Team A:</span>{" "}
          {metrics.teams.a.buildings_built.length} buildings total
        </div>
        <div>
          <span className="text-[#ff7043]">Team B:</span>{" "}
          {metrics.teams.b.buildings_built.length} buildings total
        </div>
      </div>
    </div>
  );
}
