import { platformGet } from "@/lib/platform-api";
import { NextRequest, NextResponse } from "next/server";

interface PlatformMatch {
  id: string;
  teamAName?: string;
  teamBName?: string;
  triggeredBy?: string;
  [key: string]: unknown;
}

/**
 * The platform's ?team= filter is unreliable, so we fetch larger batches
 * and filter server-side by team name substring match.
 */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const teamFilter = sp.get("team")?.toLowerCase().trim() ?? "";
  const typeFilter = sp.get("type") ?? "";
  const wantedLimit = Math.min(Number(sp.get("limit")) || 20, 100);
  const startCursor = sp.get("cursor") ?? undefined;

  try {
    const collected: PlatformMatch[] = [];
    let cursor: string | undefined = startCursor;
    let pages = 0;
    const maxPages = teamFilter ? 10 : 1;

    while (collected.length < wantedLimit && pages < maxPages) {
      const params: Record<string, string> = { limit: "100" };
      if (typeFilter) params.type = typeFilter;
      if (cursor) params.cursor = cursor;

      const data = await platformGet("/api/matches", params);
      const batch: PlatformMatch[] = data.matches ?? [];
      cursor = data.nextCursor ?? undefined;
      pages++;

      for (const m of batch) {
        if (teamFilter) {
          const a = (m.teamAName ?? "").toLowerCase();
          const b = (m.teamBName ?? "").toLowerCase();
          if (!a.includes(teamFilter) && !b.includes(teamFilter)) continue;
        }
        if (typeFilter) {
          const triggered = (m.triggeredBy ?? "") as string;
          if (typeFilter === "unrated" && triggered !== "unrated") continue;
          if (typeFilter === "ladder" && triggered === "unrated") continue;
        }
        collected.push(m);
        if (collected.length >= wantedLimit) break;
      }

      if (!cursor || batch.length === 0) break;
    }

    return NextResponse.json({
      matches: collected,
      nextCursor: cursor ?? null,
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
