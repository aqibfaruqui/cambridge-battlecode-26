"use client";

import type { MatchMetrics } from "@/types/game";
import Markdown from "react-markdown";
import { useCallback, useState } from "react";

export function AnalysisPanel({ metrics }: { metrics: MatchMetrics | null }) {
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async () => {
    if (!metrics) return;
    setLoading(true);
    setError(null);
    setText("");
    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(metrics),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error((j as { error?: string }).error ?? res.statusText);
      }
      if (!res.body) throw new Error("No response body");
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const block of parts) {
          const line = block.trim();
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[DONE]") continue;
          try {
            const parsed = JSON.parse(data) as { text?: string; error?: string };
            if (parsed.error) {
              setError(parsed.error);
              break;
            }
            if (parsed.text) setText((t) => t + parsed.text);
          } catch {
            /* ignore partial JSON */
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }, [metrics]);

  return (
    <div className="flex flex-col gap-4">
      <button
        type="button"
        disabled={!metrics || loading}
        onClick={() => void run()}
        className="w-fit rounded bg-[#4fc3f7]/20 px-4 py-2 font-mono text-[12px] text-[#4fc3f7] hover:bg-[#4fc3f7]/30 disabled:opacity-40"
      >
        {loading ? "Analyzing…" : "Analyze match"}
      </button>
      {error && <p className="font-mono text-[11px] text-red-400">{error}</p>}
      <div className="max-w-none rounded border border-[#2a2a38] bg-[#12121a] p-4 font-mono text-[12px] leading-relaxed text-[#c8c8d8] [&_h2]:mt-4 [&_h2]:font-mono [&_h2]:text-sm [&_h2]:text-[#e0e0ea] [&_p]:text-[#b8b8c8] [&_li]:text-[#b8b8c8] [&_strong]:text-[#e8e8f0]">
        {text ? (
          <Markdown>{text}</Markdown>
        ) : loading ? (
          <p className="animate-pulse text-[#8a8a9a]">Streaming analysis…</p>
        ) : (
          <p className="text-[#6a6a7a]">Run analysis to stream Claude output here.</p>
        )}
      </div>
    </div>
  );
}
