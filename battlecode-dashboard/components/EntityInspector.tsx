"use client";

import type { ParsedEntity } from "@/types/game";

interface EntityInspectorProps {
  entity: ParsedEntity | null;
  onClose: () => void;
}

export function EntityInspector({ entity, onClose }: EntityInspectorProps) {
  return (
    <div
      className={`fixed inset-y-0 right-0 z-40 w-80 max-w-[90vw] border-l border-[#2a2a38] bg-[#12121a] shadow-xl transition-transform duration-200 ${
        entity ? "pointer-events-auto translate-x-0" : "pointer-events-none translate-x-full"
      }`}
    >
      <div className="flex items-center justify-between border-b border-[#2a2a38] px-3 py-2">
        <span className="font-mono text-[12px] text-[#c8c8d8]">Entity</span>
        <button
          type="button"
          onClick={onClose}
          className="font-mono text-[11px] text-[#8a8a9a] hover:text-[#c8c8d8]"
        >
          Close
        </button>
      </div>
      {entity && (
        <dl className="space-y-2 p-3 font-mono text-[11px] text-[#a8a8b8]">
          <Row k="type" v={entity.type} />
          <Row k="id" v={String(entity.id)} />
          <Row k="team" v={entity.team.toUpperCase()} accent={entity.team === "a" ? "#4fc3f7" : "#ff7043"} />
          <Row k="position" v={`[${entity.position[0]}, ${entity.position[1]}]`} />
          <Row k="hp" v={String(entity.hp)} />
          {entity.direction && <Row k="direction" v={entity.direction} />}
          {(entity.stored_resource !== undefined && entity.stored_resource !== null) && (
            <Row k="stored" v={entity.stored_resource} />
          )}
          {entity.ammo !== undefined && <Row k="ammo" v={String(entity.ammo)} />}
          {(entity.footprint_w ?? 0) > 1 && (
            <Row k="footprint" v={`${entity.footprint_w ?? "?"}×${entity.footprint_h ?? "?"}`} />
          )}
        </dl>
      )}
    </div>
  );
}

function Row({ k, v, accent }: { k: string; v: string; accent?: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-[#6a6a7a]">{k}</dt>
      <dd className="text-right" style={accent ? { color: accent } : undefined}>
        {v}
      </dd>
    </div>
  );
}
