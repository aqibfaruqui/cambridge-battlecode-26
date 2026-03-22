import { platformFetchReplayBinary } from "@/lib/platform-api";
import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const matchId = req.nextUrl.searchParams.get("matchId");
  const game = req.nextUrl.searchParams.get("game");

  if (!matchId || !game) {
    return NextResponse.json({ error: "Missing matchId or game" }, { status: 400 });
  }

  try {
    const buf = await platformFetchReplayBinary(matchId, Number(game));
    return new NextResponse(buf, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="match-${matchId}-game${game}.replay26"`,
      },
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ error: msg }, { status: 502 });
  }
}
