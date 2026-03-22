"use client";

import { useState } from "react";

export function RawJsonViewer({ data }: { data: unknown }) {
  return (
    <div className="overflow-x-auto rounded border border-[#2a2a38] bg-[#0a0a0f] p-2 font-mono text-[11px] text-[#a8a8b8]">
      <JsonNode value={data} depth={0} keyName="root" />
    </div>
  );
}

function JsonNode({
  value,
  depth,
  keyName,
}: {
  value: unknown;
  depth: number;
  keyName: string;
}) {
  const [open, setOpen] = useState(depth < 2);

  if (value === null) {
    return (
      <span>
        <span className="text-[#6a6a7a]">{keyName}: </span>
        <span className="text-[#9575cd]">null</span>
      </span>
    );
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <span>
        <span className="text-[#6a6a7a]">{keyName}: </span>
        <span className="text-[#4fc3f7]">{String(value)}</span>
      </span>
    );
  }
  if (typeof value === "string") {
    const truncated = value.length > 200 ? `${value.slice(0, 200)}…` : value;
    return (
      <span>
        <span className="text-[#6a6a7a]">{keyName}: </span>
        <span className="text-[#ff7043]">&quot;{truncated}&quot;</span>
      </span>
    );
  }
  if (Array.isArray(value)) {
    return (
      <div className="ml-0">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="text-left text-[#8a8a9a] hover:text-[#c8c8d8]"
        >
          {open ? "▼" : "▶"} {keyName}: [{value.length}]
        </button>
        {open && (
          <div className="ml-4 border-l border-[#2a2a38] pl-2">
            {value.slice(0, 500).map((item, i) => (
              <div key={i} className="py-0.5">
                <JsonNode value={item} depth={depth + 1} keyName={`[${i}]`} />
              </div>
            ))}
            {value.length > 500 && (
              <div className="text-[#6a6a7a]">… {value.length - 500} more items</div>
            )}
          </div>
        )}
      </div>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return (
      <div className="ml-0">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="text-left text-[#8a8a9a] hover:text-[#c8c8d8]"
        >
          {open ? "▼" : "▶"} {keyName}: {"{"}
          {entries.length} keys{"}"}
        </button>
        {open && (
          <div className="ml-4 border-l border-[#2a2a38] pl-2">
            {entries.slice(0, 400).map(([k, v]) => (
              <div key={k} className="py-0.5">
                <JsonNode value={v} depth={depth + 1} keyName={k} />
              </div>
            ))}
            {entries.length > 400 && (
              <div className="text-[#6a6a7a]">… {entries.length - 400} more keys</div>
            )}
          </div>
        )}
      </div>
    );
  }
  return (
    <span>
      {keyName}: {String(value)}
    </span>
  );
}
