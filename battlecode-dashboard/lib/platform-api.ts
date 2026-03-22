import { readFile } from "fs/promises";
import { join } from "path";
import { homedir } from "os";

const API_BASE = process.env.CAMBC_API_URL ?? "https://game.battlecode.cam";
const CREDS_PATH = join(homedir(), ".cambc", "credentials.json");

async function getToken(): Promise<string> {
  const raw = await readFile(CREDS_PATH, "utf-8");
  const creds = JSON.parse(raw);
  const token = creds?.token;
  if (!token) throw new Error("Not logged in. Run: cambc login");
  return token;
}

function authHeaders(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

export async function platformGet(path: string, params?: Record<string, string>) {
  const token = await getToken();
  const url = new URL(path, API_BASE);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v) url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString(), { headers: authHeaders(token) });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Platform API ${res.status}: ${text}`);
  }
  return res.json();
}

export async function platformFetchReplayUrl(matchId: string, game: number): Promise<string> {
  const data = await platformGet("/api/matches/replay", {
    matchId,
    game: String(game),
  });
  if (!data.url) throw new Error("No replay URL returned");
  return data.url;
}

export async function platformFetchReplayBinary(matchId: string, game: number): Promise<ArrayBuffer> {
  const url = await platformFetchReplayUrl(matchId, game);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch replay binary: ${res.status}`);
  return res.arrayBuffer();
}
