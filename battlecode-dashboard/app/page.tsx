"use client";

import { ReplayUploader } from "@/components/ReplayUploader";
import { useReplay } from "@/contexts/replay-context";
import { generateMockReplay } from "@/lib/mock-replay";
import { decodeReplay26 } from "@/lib/replay26-decoder";
import { parseReplayJson } from "@/lib/replay-parser";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

export default function HomePage() {
  const { setReplay } = useReplay();
  const router = useRouter();

  const loadJson = useCallback(
    (text: string) => {
      try {
        const raw = JSON.parse(text) as unknown;
        const parsed = parseReplayJson(raw);
        parsed.raw = raw;
        setReplay(parsed);
        router.push("/match");
      } catch (e) {
        alert(e instanceof Error ? e.message : "Invalid replay JSON");
      }
    },
    [router, setReplay],
  );

  const loadBinary = useCallback(
    (buf: ArrayBuffer) => {
      try {
        const parsed = decodeReplay26(buf);
        setReplay(parsed);
        router.push("/match");
      } catch (e) {
        alert(e instanceof Error ? e.message : "Failed to decode .replay26");
      }
    },
    [router, setReplay],
  );

  const loadSample = useCallback(() => {
    setReplay(generateMockReplay());
    router.push("/match");
  }, [router, setReplay]);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-4 py-16">
      <header className="mb-10 text-center">
        <h1 className="font-data text-lg tracking-tight text-[#e8e8f0]">
          Cambridge Battlecode
        </h1>
        <p className="mt-1 font-data text-[11px] text-[#8a8a9a]">
          Replay dashboard — localhost analysis tool
        </p>
      </header>
      <ReplayUploader onLoadJson={loadJson} onLoadBinary={loadBinary} onLoadSample={loadSample} />
      <div className="mt-8 flex flex-col items-center gap-2">
        <Link
          href="/browse"
          className="rounded border border-[#4fc3f7]/30 px-4 py-2 font-data text-[11px] text-[#4fc3f7] hover:border-[#4fc3f7]/60 hover:bg-[#4fc3f7]/10"
        >
          Browse platform matches
        </Link>
        <p className="font-data text-[10px] text-[#5a5a6a]">
          or upload a <span className="text-[#6a6a8a]">.replay26</span> / <span className="text-[#6a6a8a]">.json</span> file above
        </p>
      </div>
      <p className="mt-4 text-center">
        <Link href="/match" className="font-data text-[10px] text-[#4fc3f7]/70 hover:text-[#4fc3f7]">
          Open match view (requires loaded replay)
        </Link>
      </p>
    </main>
  );
}
