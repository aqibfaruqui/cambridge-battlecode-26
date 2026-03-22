"use client";

import type { MatchMetrics } from "@/types/game";

export function StrategyComparison({ metrics }: { metrics: MatchMetrics }) {
  const a = metrics.teams.a;
  const b = metrics.teams.b;
  const rows: { label: string; a: string; b: string }[] = [
    { label: "Peak Ti", a: String(a.peak_titanium), b: String(b.peak_titanium) },
    { label: "Peak Ax", a: String(a.peak_axionite), b: String(b.peak_axionite) },
    { label: "Final scale %", a: String(a.final_scale), b: String(b.final_scale) },
    { label: "Harvesters built", a: String(a.total_harvesters_built), b: String(b.total_harvesters_built) },
    { label: "Gunners built", a: String(a.total_gunners_built), b: String(b.total_gunners_built) },
    { label: "Conveyors", a: String(a.total_conveyors_built), b: String(b.total_conveyors_built) },
    { label: "Builders spawned", a: String(a.total_builders_spawned), b: String(b.total_builders_spawned) },
    { label: "Self-destructs", a: String(a.total_self_destructs), b: String(b.total_self_destructs) },
    { label: "SD → core hit %", a: pct(a.self_destruct_efficiency), b: pct(b.self_destruct_efficiency) },
    { label: "Turret shots", a: String(a.turret_shots_fired), b: String(b.turret_shots_fired) },
    { label: "Turrets never fired", a: String(a.turrets_that_never_fired), b: String(b.turrets_that_never_fired) },
    {
      label: "Harvesters w/o chain (est.)",
      a: String(a.harvesters_without_chain),
      b: String(b.harvesters_without_chain),
    },
  ];
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div className="rounded border border-[#4fc3f7]/30 bg-[#12121a] p-3">
        <h3 className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-wide text-[#4fc3f7]">
          Team A
        </h3>
        <ul className="space-y-1 font-mono text-[11px] text-[#a8a8b8]">
          {rows.map((r) => (
            <li key={r.label} className="flex justify-between gap-2">
              <span className="text-[#6a6a7a]">{r.label}</span>
              <span className="text-[#4fc3f7]">{r.a}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded border border-[#ff7043]/30 bg-[#12121a] p-3">
        <h3 className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-wide text-[#ff7043]">
          Team B
        </h3>
        <ul className="space-y-1 font-mono text-[11px] text-[#a8a8b8]">
          {rows.map((r) => (
            <li key={`b-${r.label}`} className="flex justify-between gap-2">
              <span className="text-[#6a6a7a]">{r.label}</span>
              <span className="text-[#ff7043]">{r.b}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function pct(x: number) {
  return `${(x * 100).toFixed(1)}%`;
}
