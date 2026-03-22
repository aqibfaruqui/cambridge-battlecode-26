"use client";

import { useCallback, useState } from "react";

interface ReplayUploaderProps {
  onLoadJson: (text: string) => void;
  onLoadBinary: (buf: ArrayBuffer) => void;
  onLoadSample: () => void;
}

export function ReplayUploader({ onLoadJson, onLoadBinary, onLoadSample }: ReplayUploaderProps) {
  const [paste, setPaste] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      try {
        if (file.name.endsWith(".replay26")) {
          const buf = await file.arrayBuffer();
          onLoadBinary(buf);
        } else {
          const text = await file.text();
          onLoadJson(text);
        }
      } catch {
        setError("Could not read file");
      }
    },
    [onLoadJson, onLoadBinary],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDrag(false);
      const f = e.dataTransfer.files[0];
      if (!f) return;
      if (
        f.name.endsWith(".json") ||
        f.name.endsWith(".replay26") ||
        f.type === "application/json"
      ) {
        void handleFile(f);
      } else {
        setError("Drop a .json or .replay26 file");
      }
    },
    [handleFile],
  );

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-6">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={`rounded-lg border-2 border-dashed p-10 text-center transition-colors ${
          drag ? "border-[#4fc3f7] bg-[#12121a]" : "border-[#2a2a38] bg-[#12121a]"
        }`}
      >
        <p className="mb-2 font-mono text-[12px] text-[#8a8a9a]">
          Drop <span className="text-[#4fc3f7]">.replay26</span> or{" "}
          <span className="text-[#4fc3f7]">.json</span> here
        </p>
        <label className="inline-block cursor-pointer rounded bg-[#2a2a38] px-4 py-2 font-mono text-[11px] text-[#c8c8d8] hover:bg-[#3a3a48]">
          Choose file
          <input
            type="file"
            accept=".replay26,.json,application/json,application/octet-stream"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleFile(f);
            }}
          />
        </label>
      </div>

      <div>
        <label className="mb-1 block font-mono text-[11px] text-[#8a8a9a]">Paste JSON</label>
        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          rows={8}
          placeholder='{"map": {...}, "rounds": [...]}'
          className="w-full resize-y rounded border border-[#2a2a38] bg-[#0a0a0f] p-3 font-mono text-[11px] text-[#c8c8d8] placeholder:text-[#5a5a6a] focus:border-[#4fc3f7] focus:outline-none"
        />
        <button
          type="button"
          onClick={() => {
            setError(null);
            if (!paste.trim()) {
              setError("Paste JSON first");
              return;
            }
            onLoadJson(paste);
          }}
          className="mt-2 rounded bg-[#4fc3f7]/20 px-4 py-2 font-mono text-[11px] text-[#4fc3f7] hover:bg-[#4fc3f7]/30"
        >
          Load from paste
        </button>
      </div>

      <button
        type="button"
        onClick={() => {
          setError(null);
          onLoadSample();
        }}
        className="rounded border border-[#ff7043]/40 bg-[#ff7043]/10 px-4 py-2 font-mono text-[11px] text-[#ff7043] hover:bg-[#ff7043]/20"
      >
        Load sample replay
      </button>

      {error && <p className="font-mono text-[11px] text-red-400">{error}</p>}
    </div>
  );
}
