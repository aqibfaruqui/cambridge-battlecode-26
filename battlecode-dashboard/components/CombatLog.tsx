"use client";

import type { GameEvent, GameEventType, MatchMetrics, ParsedReplay, TeamId } from "@/types/game";
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
import { useEffect, useMemo, useState } from "react";

const COMBAT_TYPES: GameEventType[] = [
  "fire",
  "self_destruct",
  "damage",
  "launch",
  "destroy",
];

export function CombatLog({ replay, metrics }: { replay: ParsedReplay; metrics: MatchMetrics }) {
  const all = useMemo(() => {
    const evs: GameEvent[] = [];
    for (const r of replay.rounds) {
      evs.push(...r.events);
    }
    return evs.sort((a, b) => a.round - b.round || a.type.localeCompare(b.type));
  }, [replay.rounds]);

  const [teamF, setTeamF] = useState<"both" | TeamId>("both");
  const [typeF, setTypeF] = useState<GameEventType | "all">("all");
  const [rMin, setRMin] = useState(1);
  const [rMax, setRMax] = useState(1);

  useEffect(() => {
    const last = replay.rounds[replay.rounds.length - 1]?.round_number ?? replay.rounds.length;
    setRMax(last);
    setRMin(1);
  }, [replay]);

  const filtered = useMemo(() => {
    return all.filter((e) => {
      if (!COMBAT_TYPES.includes(e.type)) return false;
      if (teamF !== "both" && e.team !== teamF) return false;
      if (typeF !== "all" && e.type !== typeF) return false;
      if (e.round < rMin || e.round > rMax) return false;
      return true;
    });
  }, [all, teamF, typeF, rMin, rMax]);

  const damageChart = useMemo(() => {
    const n = metrics.total_rounds;
    const data: { round: number; dmgA: number; dmgB: number }[] = [];
    for (let i = 0; i < n; i++) {
      const roundNum = replay.rounds[i]?.round_number ?? i + 1;
      data.push({ round: roundNum, dmgA: 0, dmgB: 0 });
    }
    for (const e of all) {
      if (e.type !== "damage" || typeof e.damage !== "number") continue;
      const idx = replay.rounds.findIndex((rr) => rr.round_number === e.round);
      if (idx < 0 || idx >= data.length) continue;
      const target = e.target ?? e.position;
      if (!target) continue;
      const coreA = replay.rounds[idx].team_a.entities.find((x) => x.type === "core");
      const coreB = replay.rounds[idx].team_b.entities.find((x) => x.type === "core");
      const hitA =
        coreA &&
        target[0] >= coreA.position[0] &&
        target[0] < coreA.position[0] + (coreA.footprint_w ?? 3) &&
        target[1] >= coreA.position[1] &&
        target[1] < coreA.position[1] + (coreA.footprint_h ?? 3);
      const hitB =
        coreB &&
        target[0] >= coreB.position[0] &&
        target[0] < coreB.position[0] + (coreB.footprint_w ?? 3) &&
        target[1] >= coreB.position[1] &&
        target[1] < coreB.position[1] + (coreB.footprint_h ?? 3);
      if (hitA) data[idx].dmgA += e.damage;
      if (hitB) data[idx].dmgB += e.damage;
    }
    return data;
  }, [all, metrics.total_rounds, replay.rounds]);

  const kills = useMemo(() => {
    return all.filter((e) => e.type === "destroy").slice(-40).reverse();
  }, [all]);

  const sdEff = useMemo(() => {
    const a = metrics.teams.a;
    const b = metrics.teams.b;
    return [
      { team: "A", total: a.total_self_destructs, coreHits: a.core_hits, eff: a.self_destruct_efficiency },
      { team: "B", total: b.total_self_destructs, coreHits: b.core_hits, eff: b.self_destruct_efficiency },
    ];
  }, [metrics]);

  const maxR = replay.rounds[replay.rounds.length - 1]?.round_number ?? replay.rounds.length;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap gap-3 rounded border border-[#2a2a38] bg-[#12121a] p-3 font-mono text-[11px]">
        <label className="flex items-center gap-2 text-[#a8a8b8]">
          Team
          <select
            value={teamF}
            onChange={(e) => setTeamF(e.target.value as typeof teamF)}
            className="rounded border border-[#2a2a38] bg-[#0a0a0f] px-2 py-1 text-[#c8c8d8]"
          >
            <option value="both">Both</option>
            <option value="a">A</option>
            <option value="b">B</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-[#a8a8b8]">
          Action
          <select
            value={typeF}
            onChange={(e) => setTypeF(e.target.value as typeof typeF)}
            className="rounded border border-[#2a2a38] bg-[#0a0a0f] px-2 py-1 text-[#c8c8d8]"
          >
            <option value="all">All combat</option>
            {COMBAT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-[#a8a8b8]">
          Round min
          <input
            type="number"
            min={1}
            max={maxR}
            value={rMin}
            onChange={(e) => setRMin(Number(e.target.value))}
            className="w-20 rounded border border-[#2a2a38] bg-[#0a0a0f] px-2 py-1 text-[#c8c8d8]"
          />
        </label>
        <label className="flex items-center gap-2 text-[#a8a8b8]">
          Round max
          <input
            type="number"
            min={1}
            max={maxR}
            value={rMax}
            onChange={(e) => setRMax(Number(e.target.value))}
            className="w-20 rounded border border-[#2a2a38] bg-[#0a0a0f] px-2 py-1 text-[#c8c8d8]"
          />
        </label>
      </div>

      <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
        <h3 className="mb-2 font-mono text-[11px] uppercase text-[#8a8a9a]">Damage to cores (from damage events)</h3>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={damageChart}>
            <CartesianGrid stroke="#2a2a38" />
            <XAxis dataKey="round" stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <YAxis stroke="#4a4a5a" tick={{ fill: "#8a8a9a", fontSize: 10 }} />
            <Tooltip contentStyle={{ backgroundColor: "#1a1a24", border: "1px solid #2a2a38", fontSize: 10 }} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line type="stepAfter" dataKey="dmgA" name="→ Core A" stroke="#4fc3f7" dot={false} strokeWidth={1.5} />
            <Line type="stepAfter" dataKey="dmgB" name="→ Core B" stroke="#ff7043" dot={false} strokeWidth={1.5} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded border border-[#2a2a38] bg-[#12121a] p-3">
          <h3 className="mb-2 font-mono text-[11px] uppercase text-[#8a8a9a]">Self-destruct efficiency</h3>
          <ul className="space-y-2 font-mono text-[11px] text-[#a8a8b8]">
            {sdEff.map((x) => (
              <li key={x.team}>
                Team {x.team}: {x.coreHits}/{x.total} on enemy core tiles (
                {(x.eff * 100).toFixed(1)}%)
              </li>
            ))}
          </ul>
        </div>
        <div className="max-h-48 overflow-y-auto rounded border border-[#2a2a38] bg-[#12121a] p-3">
          <h3 className="mb-2 font-mono text-[11px] uppercase text-[#8a8a9a]">Kill feed (destroy)</h3>
          <ul className="space-y-1 font-mono text-[10px] text-[#8a8a9a]">
            {kills.length === 0 && <li>No destroy events in replay</li>}
            {kills.map((e, i) => (
              <li key={i}>
                R{e.round} {e.team.toUpperCase()} {e.type}{" "}
                {e.entity_id !== undefined ? `#${e.entity_id}` : ""}{" "}
                {e.position ? `@ [${e.position[0]},${e.position[1]}]` : ""}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="overflow-x-auto rounded border border-[#2a2a38] bg-[#12121a]">
        <h3 className="border-b border-[#2a2a38] p-3 font-mono text-[11px] uppercase text-[#8a8a9a]">
          Combat log ({filtered.length} rows)
        </h3>
        <table className="w-full font-mono text-[10px] text-[#a8a8b8]">
          <thead>
            <tr className="border-b border-[#2a2a38] text-left text-[#6a6a7a]">
              <th className="p-2">rnd</th>
              <th className="p-2">team</th>
              <th className="p-2">action</th>
              <th className="p-2">entity</th>
              <th className="p-2">target</th>
              <th className="p-2">dmg</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e, i) => (
              <tr key={i} className="border-b border-[#1a1a24]">
                <td className="p-2">{e.round}</td>
                <td className="p-2" style={{ color: e.team === "a" ? "#4fc3f7" : "#ff7043" }}>
                  {e.team.toUpperCase()}
                </td>
                <td className="p-2">{e.type}</td>
                <td className="p-2">{e.entity_id ?? "—"}</td>
                <td className="p-2">
                  {e.target
                    ? `[${e.target[0]},${e.target[1]}]`
                    : e.position
                      ? `[${e.position[0]},${e.position[1]}]`
                      : "—"}
                </td>
                <td className="p-2">{e.damage ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
