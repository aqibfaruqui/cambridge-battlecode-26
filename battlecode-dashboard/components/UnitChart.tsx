"use client";

import type { ParsedReplay } from "@/types/game";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useMemo, useState } from "react";

const COLORS = [
  "#4fc3f7",
  "#29b6f6",
  "#0288d1",
  "#ff7043",
  "#ff5722",
  "#d84315",
  "#9575cd",
  "#7cb342",
];

export function UnitChart({
  replay,
  roundIndex,
}: {
  replay: ParsedReplay;
  roundIndex: number;
}) {
  const mainTypes = useMemo(() => {
    const s = new Set<string>();
    for (const r of replay.rounds) {
      for (const e of r.team_a.entities) s.add(e.type);
      for (const e of r.team_b.entities) s.add(e.type);
    }
    return Array.from(s).sort();
  }, [replay.rounds]);

  const stackedDataA = useMemo(() => {
    return replay.rounds.map((r) => {
      const row: Record<string, number | string> = { round: r.round_number };
      const m: Record<string, number> = {};
      for (const e of r.team_a.entities) {
        m[e.type] = (m[e.type] ?? 0) + 1;
      }
      for (const t of mainTypes) {
        row[t] = m[t] ?? 0;
      }
      return row;
    });
  }, [replay.rounds, mainTypes]);

  const stackedDataB = useMemo(() => {
    return replay.rounds.map((r) => {
      const row: Record<string, number | string> = { round: r.round_number };
      const m: Record<string, number> = {};
      for (const e of r.team_b.entities) {
        m[e.type] = (m[e.type] ?? 0) + 1;
      }
      for (const t of mainTypes) {
        row[t] = m[t] ?? 0;
      }
      return row;
    });
  }, [replay.rounds, mainTypes]);

  const current = replay.rounds[Math.min(roundIndex, replay.rounds.length - 1)];
  const [sortKey, setSortKey] = useState<"type" | "hp" | "team">("type");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  const tableRows = useMemo(() => {
    const rows = [...current.team_a.entities, ...current.team_b.entities].map((e) => ({
      ...e,
    }));
    rows.sort((x, y) => {
      let c = 0;
      if (sortKey === "type") c = x.type.localeCompare(y.type);
      else if (sortKey === "hp") c = x.hp - y.hp;
      else c = x.team.localeCompare(y.team);
      return sortDir === "asc" ? c : -c;
    });
    return rows;
  }, [current, sortKey, sortDir]);

  const quadrantData = useMemo(() => {
    const w = replay.map.width;
    const h = replay.map.height;
    const midX = w / 2;
    const midY = h / 2;
    const q = { a: [0, 0, 0, 0] as number[], b: [0, 0, 0, 0] as number[] };
    for (const r of replay.rounds) {
      for (const team of ["a", "b"] as const) {
        const st = team === "a" ? r.team_a : r.team_b;
        for (const e of st.entities) {
          if (e.type !== "builder_bot") continue;
          const [x, y] = e.position;
          let qi = 0;
          if (x >= midX && y < midY) qi = 1;
          else if (x < midX && y >= midY) qi = 2;
          else if (x >= midX && y >= midY) qi = 3;
          q[team][qi]++;
        }
      }
    }
    return [
      { name: "NW", a: q.a[0], b: q.b[0] },
      { name: "NE", a: q.a[1], b: q.b[1] },
      { name: "SW", a: q.a[2], b: q.b[2] },
      { name: "SE", a: q.a[3], b: q.b[3] },
    ];
  }, [replay]);

  const spawnBuckets = useMemo(() => {
    const bucket = 50;
    const maxR = replay.rounds.length;
    const rows: { label: string; a: number; b: number }[] = [];
    for (let start = 0; start < maxR; start += bucket) {
      let a = 0;
      let b = 0;
      for (let i = start; i < Math.min(start + bucket, maxR); i++) {
        for (const ev of replay.rounds[i].events) {
          if (ev.type === "spawn" && ev.team === "a") a++;
          if (ev.type === "spawn" && ev.team === "b") b++;
        }
      }
      rows.push({ label: `${start + 1}-${Math.min(start + bucket, maxR)}`, a, b });
    }
    return rows;
  }, [replay]);

  const toggleSort = (k: typeof sortKey) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setSortDir("asc");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
        <h3 className="mb-2 font-mono text-[11px] uppercase text-[#4fc3f7]">Team A — units by type</h3>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={stackedDataA}>
            <CartesianGrid stroke="#2a2a38" />
            <XAxis dataKey="round" stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <YAxis stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1a1a24",
                border: "1px solid #2a2a38",
                fontSize: 10,
              }}
            />
            <Legend wrapperStyle={{ fontSize: 9 }} />
            {mainTypes.map((t, i) => (
              <Area
                key={`a-${t}`}
                type="stepAfter"
                dataKey={t}
                name={t}
                stackId="1"
                stroke={COLORS[i % COLORS.length]}
                fill={COLORS[i % COLORS.length]}
                fillOpacity={0.45}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
        <h3 className="mb-2 mt-4 font-mono text-[11px] uppercase text-[#ff7043]">Team B — units by type</h3>
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={stackedDataB}>
            <CartesianGrid stroke="#2a2a38" />
            <XAxis dataKey="round" stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <YAxis stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <Tooltip
              contentStyle={{
                backgroundColor: "#1a1a24",
                border: "1px solid #2a2a38",
                fontSize: 10,
              }}
            />
            <Legend wrapperStyle={{ fontSize: 9 }} />
            {mainTypes.map((t, i) => (
              <Area
                key={`b-${t}`}
                type="stepAfter"
                dataKey={t}
                name={t}
                stackId="1"
                stroke={COLORS[i % COLORS.length]}
                fill={COLORS[i % COLORS.length]}
                fillOpacity={0.45}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
        <h3 className="mb-2 font-mono text-[11px] uppercase text-[#8a8a9a]">
          Builder time by quadrant (visit-weighted, all rounds)
        </h3>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={quadrantData}>
            <CartesianGrid stroke="#2a2a38" />
            <XAxis dataKey="name" stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <YAxis stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <Tooltip contentStyle={{ backgroundColor: "#1a1a24", border: "1px solid #2a2a38" }} />
            <Area type="monotone" dataKey="a" name="Team A" stackId="1" stroke="#4fc3f7" fill="#4fc3f7" fillOpacity={0.4} />
            <Area type="monotone" dataKey="b" name="Team B" stackId="1" stroke="#ff7043" fill="#ff7043" fillOpacity={0.4} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
        <h3 className="mb-2 font-mono text-[11px] uppercase text-[#8a8a9a]">
          Spawn events per {50} rounds (proxy for builder spawn rate)
        </h3>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={spawnBuckets}>
            <CartesianGrid stroke="#2a2a38" />
            <XAxis dataKey="label" stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 9 }} />
            <YAxis stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <Tooltip contentStyle={{ backgroundColor: "#1a1a24", border: "1px solid #2a2a38" }} />
            <Area type="step" dataKey="a" name="A spawns" stackId="s" stroke="#4fc3f7" fill="#4fc3f7" fillOpacity={0.35} />
            <Area type="step" dataKey="b" name="B spawns" stackId="s" stroke="#ff7043" fill="#ff7043" fillOpacity={0.35} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="overflow-x-auto rounded border border-[#2a2a38] bg-[#12121a]">
        <h3 className="border-b border-[#2a2a38] p-3 font-mono text-[11px] uppercase text-[#8a8a9a]">
          Entities at round {current.round_number}
        </h3>
        <table className="w-full font-mono text-[11px] text-[#a8a8b8]">
          <thead>
            <tr className="border-b border-[#2a2a38] text-left text-[#6a6a7a]">
              <th className="cursor-pointer p-2" onClick={() => toggleSort("type")}>
                type {sortKey === "type" ? (sortDir === "asc" ? "↑" : "↓") : ""}
              </th>
              <th className="p-2">id</th>
              <th className="cursor-pointer p-2" onClick={() => toggleSort("team")}>
                team {sortKey === "team" ? (sortDir === "asc" ? "↑" : "↓") : ""}
              </th>
              <th className="cursor-pointer p-2" onClick={() => toggleSort("hp")}>
                hp {sortKey === "hp" ? (sortDir === "asc" ? "↑" : "↓") : ""}
              </th>
              <th className="p-2">pos</th>
            </tr>
          </thead>
          <tbody>
            {tableRows.map((e) => (
              <tr key={`${e.team}-${e.id}`} className="border-b border-[#1a1a24]">
                <td className="p-2">{e.type}</td>
                <td className="p-2">{e.id}</td>
                <td className="p-2" style={{ color: e.team === "a" ? "#4fc3f7" : "#ff7043" }}>
                  {e.team.toUpperCase()}
                </td>
                <td className="p-2">{e.hp}</td>
                <td className="p-2">
                  [{e.position[0]},{e.position[1]}]
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
