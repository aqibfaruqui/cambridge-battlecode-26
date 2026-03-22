import { NextRequest } from "next/server";
import { analyzeMatchStream } from "@/lib/claude-client";
import type { MatchMetrics } from "@/types/game";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  let metrics: MatchMetrics;
  try {
    metrics = (await req.json()) as MatchMetrics;
  } catch {
    return new Response(JSON.stringify({ error: "Invalid JSON body" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  if (!metrics || typeof metrics !== "object" || !metrics.teams) {
    return new Response(JSON.stringify({ error: "Body must be MatchMetrics" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const stream = await analyzeMatchStream(metrics);
    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    const status = msg.includes("ANTHROPIC_API_KEY") ? 503 : 500;
    return new Response(JSON.stringify({ error: msg }), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  }
}
