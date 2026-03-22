"use client";

import { useReplay } from "@/contexts/replay-context";
import { decodeReplay26 } from "@/lib/replay26-decoder";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

interface PlatformMatch {
  id: string;
  teamAName: string;
  teamBName: string;
  teamAId: string;
  teamBId: string;
  winnerId?: string;
  scoreA: number;
  scoreB: number;
  status: string;
  triggeredBy?: string;
  completedAt?: string;
  createdAt?: string;
  rated?: boolean;
}

interface MatchGame {
  gameNumber: number;
  mapName: string;
  winnerId?: string;
  winCondition?: string;
  turnsPlayed?: number;
}

interface MatchDetail {
  match: PlatformMatch;
  games: MatchGame[];
}

export default function BrowsePage() {
  const { setReplay } = useReplay();
  const router = useRouter();

  // Search state
  const [teamName, setTeamName] = useState("");
  const [matchType, setMatchType] = useState<"" | "ladder" | "unrated">("");
  const [limit, setLimit] = useState(20);

  // Results state
  const [matches, setMatches] = useState<PlatformMatch[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail view state
  const [detail, setDetail] = useState<MatchDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Replay download state
  const [downloading, setDownloading] = useState<string | null>(null);

  const fetchMatches = useCallback(async (cursor?: string) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (teamName.trim()) params.set("team", teamName.trim());
      if (matchType) params.set("type", matchType);
      params.set("limit", String(limit));
      if (cursor) params.set("cursor", cursor);

      const res = await fetch(`/api/platform/matches?${params}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);

      if (cursor) {
        setMatches((prev) => [...prev, ...(data.matches ?? [])]);
      } else {
        setMatches(data.matches ?? []);
      }
      setNextCursor(data.nextCursor ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [teamName, matchType, limit]);

  const openDetail = useCallback(async (matchId: string) => {
    setDetailLoading(true);
    setDetail(null);
    try {
      const res = await fetch(`/api/platform/matches/${matchId}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setDetail(data as MatchDetail);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const loadReplay = useCallback(async (matchId: string, gameNum: number) => {
    const key = `${matchId}-${gameNum}`;
    setDownloading(key);
    try {
      const res = await fetch(`/api/platform/replay?matchId=${matchId}&game=${gameNum}`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: "Unknown error" }));
        throw new Error(body.error ?? `HTTP ${res.status}`);
      }
      const buf = await res.arrayBuffer();
      const parsed = decodeReplay26(buf);
      setReplay(parsed);
      router.push("/match");
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to load replay");
    } finally {
      setDownloading(null);
    }
  }, [router, setReplay]);

  // Load on mount with stored team name
  useEffect(() => {
    const stored = localStorage.getItem("bc-team-name");
    if (stored) setTeamName(stored);
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (teamName.trim()) localStorage.setItem("bc-team-name", teamName.trim());
    fetchMatches();
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col px-4 py-8">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-data text-lg tracking-tight text-[#e8e8f0]">
            Match Browser
          </h1>
          <p className="mt-0.5 font-data text-[11px] text-[#6a6a7a]">
            Browse platform matches and load replays for analysis
          </p>
        </div>
        <Link
          href="/"
          className="rounded border border-[#2a2a38] px-3 py-1.5 font-data text-[10px] text-[#8a8a9a] hover:border-[#4fc3f7]/50 hover:text-[#c8c8d8]"
        >
          Upload local
        </Link>
      </header>

      {/* Search form */}
      <form onSubmit={handleSearch} className="mb-6 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="font-data text-[10px] text-[#8a8a9a]">Team name</span>
          <input
            type="text"
            value={teamName}
            onChange={(e) => setTeamName(e.target.value)}
            placeholder="e.g. REDACTED AI Lab"
            className="w-56 rounded border border-[#2a2a38] bg-[#0a0a0f] px-3 py-1.5 font-data text-[11px] text-[#e8e8f0] placeholder:text-[#4a4a5a] focus:border-[#4fc3f7]/50 focus:outline-none"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-data text-[10px] text-[#8a8a9a]">Type</span>
          <select
            value={matchType}
            onChange={(e) => setMatchType(e.target.value as typeof matchType)}
            className="rounded border border-[#2a2a38] bg-[#0a0a0f] px-3 py-1.5 font-data text-[11px] text-[#e8e8f0] focus:outline-none"
          >
            <option value="">All</option>
            <option value="ladder">Ladder</option>
            <option value="unrated">Unrated</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-data text-[10px] text-[#8a8a9a]">Limit</span>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded border border-[#2a2a38] bg-[#0a0a0f] px-3 py-1.5 font-data text-[11px] text-[#e8e8f0] focus:outline-none"
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={loading}
          className="rounded bg-[#4fc3f7]/15 px-4 py-1.5 font-data text-[11px] text-[#4fc3f7] hover:bg-[#4fc3f7]/25 disabled:opacity-50"
        >
          {loading ? "Searching..." : "Search"}
        </button>
      </form>

      {error && (
        <div className="mb-4 rounded border border-red-900/50 bg-red-900/10 px-3 py-2 font-data text-[11px] text-red-400">
          {error}
        </div>
      )}

      {/* Match list + detail side-by-side */}
      <div className="flex min-h-0 flex-1 gap-4">
        {/* Match list */}
        <div className="min-w-0 flex-1">
          {matches.length > 0 && (
            <div className="overflow-hidden rounded border border-[#2a2a38]">
              <table className="w-full font-data text-[11px]">
                <thead>
                  <tr className="border-b border-[#2a2a38] bg-[#12121a] text-left text-[10px] text-[#6a6a7a]">
                    <th className="px-2 py-1.5">Match</th>
                    <th className="px-2 py-1.5">Team A</th>
                    <th className="px-2 py-1.5 text-center">Score</th>
                    <th className="px-2 py-1.5">Team B</th>
                    <th className="px-2 py-1.5">Type</th>
                    <th className="px-2 py-1.5">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {matches.map((m) => {
                    const aWon = m.winnerId === m.teamAId;
                    const bWon = m.winnerId === m.teamBId;
                    const isSelected = detail?.match.id === m.id;
                    return (
                      <tr
                        key={m.id}
                        onClick={() => openDetail(m.id)}
                        className={`cursor-pointer border-b border-[#1a1a24] transition-colors ${
                          isSelected
                            ? "bg-[#4fc3f7]/10"
                            : "hover:bg-[#16161e]"
                        }`}
                      >
                        <td className="px-2 py-1.5 text-[#6a6a7a]">
                          {m.id.slice(0, 8)}
                        </td>
                        <td className={`px-2 py-1.5 ${aWon ? "text-[#66bb6a]" : bWon ? "text-[#ef5350]" : "text-[#a8a8b8]"}`}>
                          {m.teamAName}
                        </td>
                        <td className="px-2 py-1.5 text-center text-[#c8c8d8]">
                          {m.scoreA}-{m.scoreB}
                        </td>
                        <td className={`px-2 py-1.5 ${bWon ? "text-[#66bb6a]" : aWon ? "text-[#ef5350]" : "text-[#a8a8b8]"}`}>
                          {m.teamBName}
                        </td>
                        <td className="px-2 py-1.5 text-[#6a6a7a]">
                          {m.triggeredBy === "unrated" ? "UR" : m.triggeredBy ?? "—"}
                        </td>
                        <td className="px-2 py-1.5 text-[#6a6a7a]">
                          {(m.completedAt ?? m.createdAt ?? "").slice(0, 16).replace("T", " ")}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {nextCursor && (
            <button
              type="button"
              onClick={() => fetchMatches(nextCursor)}
              disabled={loading}
              className="mt-3 w-full rounded border border-[#2a2a38] py-1.5 font-data text-[10px] text-[#8a8a9a] hover:bg-[#16161e] disabled:opacity-50"
            >
              Load more
            </button>
          )}

          {matches.length === 0 && !loading && !error && (
            <div className="mt-12 text-center font-data text-[11px] text-[#6a6a7a]">
              Enter a team name and search to browse matches.
            </div>
          )}
        </div>

        {/* Detail panel */}
        {(detail || detailLoading) && (
          <div className="w-80 shrink-0 overflow-y-auto rounded border border-[#2a2a38] bg-[#12121a] p-3">
            {detailLoading ? (
              <div className="py-8 text-center font-data text-[11px] text-[#6a6a7a]">Loading match...</div>
            ) : detail ? (
              <MatchDetailPanel
                detail={detail}
                downloading={downloading}
                onLoadReplay={loadReplay}
              />
            ) : null}
          </div>
        )}
      </div>
    </main>
  );
}

function MatchDetailPanel({
  detail,
  downloading,
  onLoadReplay,
}: {
  detail: MatchDetail;
  downloading: string | null;
  onLoadReplay: (matchId: string, gameNum: number) => void;
}) {
  const m = detail.match;
  const aWon = m.winnerId === m.teamAId;
  const bWon = m.winnerId === m.teamBId;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="font-data text-[12px] text-[#e8e8f0]">Match details</h3>
        <span className={`rounded px-1.5 py-0.5 font-data text-[9px] ${
          m.status === "complete" ? "bg-green-900/30 text-green-400" :
          m.status === "error" ? "bg-red-900/30 text-red-400" :
          "bg-yellow-900/30 text-yellow-400"
        }`}>
          {m.status}
        </span>
      </div>

      <div className="space-y-1 font-data text-[10px]">
        <div className="flex justify-between">
          <span className={aWon ? "text-[#66bb6a]" : "text-[#a8a8b8]"}>{m.teamAName}</span>
          <span className="text-[#c8c8d8]">{m.scoreA} - {m.scoreB}</span>
          <span className={bWon ? "text-[#66bb6a]" : "text-[#a8a8b8]"}>{m.teamBName}</span>
        </div>
        <div className="text-[#6a6a7a]">
          ID: {m.id}
        </div>
      </div>

      {detail.games.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="font-data text-[10px] uppercase text-[#6a6a7a]">Games</h4>
          {detail.games.map((g) => {
            const key = `${m.id}-${g.gameNumber}`;
            const gWinnerIsA = g.winnerId === m.teamAId;
            const gWinnerIsB = g.winnerId === m.teamBId;
            return (
              <div
                key={g.gameNumber}
                className="flex items-center gap-2 rounded border border-[#2a2a38] bg-[#0a0a0f] px-2 py-1.5"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-data text-[10px]">
                    <span className="text-[#8a8a9a]">G{g.gameNumber}</span>
                    <span className="text-[#6a6a7a]">{g.mapName}</span>
                    <span className={gWinnerIsA ? "text-[#4fc3f7]" : gWinnerIsB ? "text-[#ff7043]" : "text-[#6a6a7a]"}>
                      {gWinnerIsA ? "A" : gWinnerIsB ? "B" : "—"}
                    </span>
                    <span className="text-[#4a4a5a]">{g.turnsPlayed}t</span>
                  </div>
                  <div className="font-data text-[9px] text-[#4a4a5a]">
                    {g.winCondition}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onLoadReplay(m.id, g.gameNumber)}
                  disabled={downloading === key}
                  className="shrink-0 rounded bg-[#4fc3f7]/15 px-2 py-1 font-data text-[9px] text-[#4fc3f7] hover:bg-[#4fc3f7]/25 disabled:opacity-50"
                >
                  {downloading === key ? "Loading..." : "Analyze"}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {detail.games.length === 0 && m.status !== "complete" && (
        <div className="py-4 text-center font-data text-[10px] text-[#6a6a7a]">
          {m.status === "queued" ? "Match queued — waiting for runner..." :
           m.status === "running" ? "Match running..." : "No game data."}
        </div>
      )}
    </div>
  );
}
