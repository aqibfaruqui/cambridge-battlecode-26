"use client";

import { AnalysisPanel } from "@/components/AnalysisPanel";
import { BuilderDistanceChart } from "@/components/BuilderDistanceChart";
import { BuildTimeline } from "@/components/BuildTimeline";
import { CombatLog } from "@/components/CombatLog";
import { CoreHpChart } from "@/components/CoreHpChart";
import { EconomyChart } from "@/components/EconomyChart";
import { EntityInspector } from "@/components/EntityInspector";
import { MapVisualization, type TeamFilter } from "@/components/MapVisualization";
import { RawJsonViewer } from "@/components/RawJsonViewer";
import { RoundSlider } from "@/components/RoundSlider";
import { StrategyComparison } from "@/components/StrategyComparison";
import { UnitChart } from "@/components/UnitChart";
import { useReplay } from "@/contexts/replay-context";
import type { ParsedEntity } from "@/types/game";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

type Tab = "map" | "econ" | "units" | "combat" | "timeline" | "analysis" | "raw";

export default function MatchPage() {
  const { replay, metrics, clearReplay } = useReplay();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("map");
  const [roundIndex, setRoundIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [teamFilter, setTeamFilter] = useState<TeamFilter>("both");
  const [selected, setSelected] = useState<ParsedEntity | null>(null);
  const [showTrails, setShowTrails] = useState(true);
  const [showDeath, setShowDeath] = useState(false);
  const [showVision, setShowVision] = useState(false);
  const [showAttack, setShowAttack] = useState(false);
  const [showFlow, setShowFlow] = useState(false);
  const trailRounds = 25;

  useEffect(() => {
    if (!replay) {
      router.replace("/");
    }
  }, [replay, router]);

  const maxIdx = replay ? replay.rounds.length - 1 : 0;

  useEffect(() => {
    if (roundIndex > maxIdx) setRoundIndex(maxIdx);
  }, [maxIdx, roundIndex]);

  useEffect(() => {
    if (!playing || !replay) return;
    const base = 450;
    const ms = Math.max(40, base / speed);
    const id = window.setInterval(() => {
      setRoundIndex((i) => (i >= maxIdx ? 0 : i + 1));
    }, ms);
    return () => clearInterval(id);
  }, [playing, replay, maxIdx, speed]);

  const round = replay?.rounds[roundIndex];

  const tabBtn = useCallback(
    (id: Tab, label: string) => (
      <button
        key={id}
        type="button"
        onClick={() => setTab(id)}
        className={`w-full px-3 py-2 text-left font-data text-[11px] transition-colors ${
          tab === id
            ? "border-l-2 border-[#4fc3f7] bg-[#1a1a24] text-[#e8e8f0]"
            : "border-l-2 border-transparent text-[#8a8a9a] hover:bg-[#16161e] hover:text-[#c8c8d8]"
        }`}
      >
        {label}
      </button>
    ),
    [tab],
  );

  if (!replay || !metrics) {
    return (
      <div className="flex min-h-screen items-center justify-center font-data text-[12px] text-[#8a8a9a]">
        Loading…
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-[#2a2a38] bg-[#12121a] px-3 py-2">
        <div className="font-data text-[12px] text-[#e8e8f0]">Battlecode analysis</div>
        <Link
          href="/"
          onClick={() => clearReplay()}
          className="rounded border border-[#2a2a38] px-2 py-1 font-data text-[10px] text-[#8a8a9a] hover:border-[#4fc3f7]/50 hover:text-[#c8c8d8]"
        >
          Upload new
        </Link>
        <Link
          href="/browse"
          className="rounded border border-[#2a2a38] px-2 py-1 font-data text-[10px] text-[#8a8a9a] hover:border-[#4fc3f7]/50 hover:text-[#c8c8d8]"
        >
          Browse matches
        </Link>
        <div className="mx-2 hidden h-4 w-px bg-[#2a2a38] sm:block" />
        <RoundSlider
          min={0}
          max={maxIdx}
          value={roundIndex}
          onChange={setRoundIndex}
          label={`Round index → #${round?.round_number ?? ""}`}
        />
        <div className="flex items-center gap-1 font-data text-[10px]">
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            className="rounded bg-[#2a2a38] px-2 py-1 text-[#c8c8d8] hover:bg-[#3a3a48]"
          >
            {playing ? "Pause" : "Play"}
          </button>
          {[1, 2, 5, 10].map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => {
                setSpeed(s);
                setPlaying(true);
              }}
              className={`rounded px-2 py-1 ${
                speed === s ? "bg-[#4fc3f7]/25 text-[#4fc3f7]" : "text-[#8a8a9a] hover:bg-[#2a2a38]"
              }`}
            >
              {s}x
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 font-data text-[10px] text-[#8a8a9a]">
          <span>Team</span>
          {(["both", "a", "b"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTeamFilter(t === "both" ? "both" : t)}
              className={`rounded px-2 py-0.5 uppercase ${
                teamFilter === t
                  ? t === "a"
                    ? "bg-[#4fc3f7]/20 text-[#4fc3f7]"
                    : t === "b"
                      ? "bg-[#ff7043]/20 text-[#ff7043]"
                      : "bg-[#2a2a38] text-[#e8e8f0]"
                  : "hover:bg-[#1a1a24]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav className="w-28 shrink-0 border-r border-[#2a2a38] bg-[#12121a] py-2">
          {tabBtn("map", "Map")}
          {tabBtn("econ", "Economy")}
          {tabBtn("units", "Units")}
          {tabBtn("combat", "Combat")}
          {tabBtn("timeline", "Timeline")}
          {tabBtn("analysis", "AI")}
          {tabBtn("raw", "Raw")}
        </nav>
        <section className="min-w-0 flex-1 overflow-auto p-3">
          {tab === "map" && (
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-3 font-data text-[10px] text-[#8a8a9a]">
                <label className="flex cursor-pointer items-center gap-1">
                  <input type="checkbox" checked={showTrails} onChange={(e) => setShowTrails(e.target.checked)} />
                  Movement trails
                </label>
                <label className="flex cursor-pointer items-center gap-1">
                  <input type="checkbox" checked={showDeath} onChange={(e) => setShowDeath(e.target.checked)} />
                  Death heatmap
                </label>
                <label className="flex cursor-pointer items-center gap-1">
                  <input type="checkbox" checked={showVision} onChange={(e) => setShowVision(e.target.checked)} />
                  Vision radius
                </label>
                <label className="flex cursor-pointer items-center gap-1">
                  <input type="checkbox" checked={showAttack} onChange={(e) => setShowAttack(e.target.checked)} />
                  Attack ranges
                </label>
                <label className="flex cursor-pointer items-center gap-1">
                  <input type="checkbox" checked={showFlow} onChange={(e) => setShowFlow(e.target.checked)} />
                  Conveyor flow
                </label>
              </div>
              <MapVisualization
                replay={replay}
                roundIndex={roundIndex}
                teamFilter={teamFilter}
                selected={selected}
                onSelect={setSelected}
                showTrails={showTrails}
                showDeathHeatmap={showDeath}
                showVision={showVision && !!selected}
                showAttackRange={showAttack && !!selected}
                showConveyorFlow={showFlow}
                trailRounds={trailRounds}
              />
              <p className="font-data text-[10px] text-[#6a6a7a]">
                Click an entity to inspect. Vision and attack overlays require a selected unit.
              </p>
            </div>
          )}
          {tab === "econ" && <EconomyChart metrics={metrics} replay={replay} />}
          {tab === "units" && <UnitChart replay={replay} roundIndex={roundIndex} />}
          {tab === "combat" && <CombatLog replay={replay} metrics={metrics} />}
          {tab === "timeline" && (
            <div className="flex flex-col gap-6">
              <CoreHpChart metrics={metrics} replay={replay} />
              <BuilderDistanceChart metrics={metrics} replay={replay} />
              <BuildTimeline metrics={metrics} />
            </div>
          )}
          {tab === "analysis" && (
            <div className="flex flex-col gap-6">
              <StrategyComparison metrics={metrics} />
              <AnalysisPanel metrics={metrics} />
            </div>
          )}
          {tab === "raw" && (
            <div>
              <p className="mb-2 font-data text-[11px] text-[#8a8a9a]">
                Parsed replay reference (truncated tree for large arrays/objects).
              </p>
              <RawJsonViewer data={replay.raw ?? replay} />
            </div>
          )}
        </section>
      </div>

      <footer className="border-t border-[#2a2a38] bg-[#12121a] px-3 py-1.5 font-data text-[10px] text-[#8a8a9a]">
        Round {round?.round_number ?? "—"} / {replay.rounds[replay.rounds.length - 1]?.round_number ?? "—"} | A:{" "}
        {round?.team_a.titanium ?? "—"} Ti | B: {round?.team_b.titanium ?? "—"} Ti | Winner:{" "}
        {replay.winner?.toUpperCase() ?? "—"} — {replay.win_reason}
      </footer>

      <EntityInspector entity={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
