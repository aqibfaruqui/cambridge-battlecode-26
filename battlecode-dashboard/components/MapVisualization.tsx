"use client";

import type { ParsedEntity, ParsedReplay, TeamId } from "@/types/game";
import { CORE_FOOTPRINT, CORE_MAX_HP, VISION_R2 } from "@/lib/game-constants";
import { computeHeatmapOverlay } from "@/components/HeatmapOverlay";
import { spritePath, tilePath, bgPath } from "@/lib/sprites";
import { useCallback, useEffect, useRef, useState } from "react";

export type TeamFilter = "both" | TeamId;

interface MapVisualizationProps {
  replay: ParsedReplay;
  roundIndex: number;
  teamFilter: TeamFilter;
  selected: ParsedEntity | null;
  onSelect: (e: ParsedEntity | null) => void;
  showTrails: boolean;
  showDeathHeatmap: boolean;
  showVision: boolean;
  showAttackRange: boolean;
  showConveyorFlow: boolean;
  trailRounds: number;
}

function dirToRad(dir: string | undefined): number {
  if (!dir) return 0;
  const d = dir.toLowerCase();
  const map: Record<string, number> = {
    east: 0,
    southeast: Math.PI / 4,
    south: Math.PI / 2,
    southwest: (3 * Math.PI) / 4,
    west: Math.PI,
    northwest: (-3 * Math.PI) / 4,
    north: -Math.PI / 2,
    northeast: -Math.PI / 4,
    centre: 0,
  };
  return map[d] ?? 0;
}

function entityCells(e: ParsedEntity): [number, number][] {
  if (e.type === "core") {
    const w = e.footprint_w ?? CORE_FOOTPRINT;
    const h = e.footprint_h ?? CORE_FOOTPRINT;
    const [x0, y0] = e.position;
    const cells: [number, number][] = [];
    for (let dy = 0; dy < h; dy++) {
      for (let dx = 0; dx < w; dx++) {
        cells.push([x0 + dx, y0 + dy]);
      }
    }
    return cells;
  }
  return [[e.position[0], e.position[1]]];
}

function visionR2ForType(t: string): number | null {
  switch (t) {
    case "core": return VISION_R2.core;
    case "builder_bot": return VISION_R2.builder_bot;
    case "gunner": return VISION_R2.gunner;
    case "sentinel": return VISION_R2.sentinel;
    case "breach": return VISION_R2.breach;
    case "launcher": return VISION_R2.launcher;
    default: return null;
  }
}

function attackR2ForType(t: string): number | null {
  if (t === "gunner") return 13;
  if (t === "sentinel") return 32;
  if (t === "breach") return VISION_R2.breach_attack;
  return null;
}

function centerOfEntity(e: ParsedEntity): [number, number] {
  if (e.type === "core") {
    const w = e.footprint_w ?? CORE_FOOTPRINT;
    const h = e.footprint_h ?? CORE_FOOTPRINT;
    const [x0, y0] = e.position;
    return [x0 + w / 2, y0 + h / 2];
  }
  return [e.position[0] + 0.5, e.position[1] + 0.5];
}

const MAX_HP: Record<string, number> = {
  core: CORE_MAX_HP, builder_bot: 30, conveyor: 20, splitter: 20,
  bridge: 20, armoured_conveyor: 50, harvester: 30, foundry: 50,
  road: 10, barrier: 30, marker: 1, gunner: 40, sentinel: 30,
  breach: 60, launcher: 30,
};

const imageCache = new Map<string, HTMLImageElement>();

function getImage(src: string): HTMLImageElement | null {
  const cached = imageCache.get(src);
  if (cached?.complete && cached.naturalWidth > 0) return cached;
  if (!cached) {
    const img = new Image();
    img.src = src;
    imageCache.set(src, img);
  }
  return null;
}

export function MapVisualization({
  replay, roundIndex, teamFilter, selected, onSelect,
  showTrails, showDeathHeatmap, showVision, showAttackRange,
  showConveyorFlow, trailRounds,
}: MapVisualizationProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Camera state: zoom level and pan offset (in CSS pixels)
  const [zoom, setZoom] = useState(1);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const dragRef = useRef<{ startX: number; startY: number; panX0: number; panY0: number } | null>(null);

  const r = replay.rounds[Math.min(roundIndex, replay.rounds.length - 1)];
  const { width: mw, height: mh, tiles } = replay.map;

  // Reset camera when replay changes
  useEffect(() => {
    setZoom(1);
    setPanX(0);
    setPanY(0);
  }, [replay]);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = wrap.getBoundingClientRect();
    const viewW = Math.max(320, rect.width);
    const viewH = Math.max(320, rect.height);

    canvas.width = viewW * dpr;
    canvas.height = viewH * dpr;
    canvas.style.width = `${viewW}px`;
    canvas.style.height = `${viewH}px`;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";

    // Clear
    ctx.fillStyle = "#0a0a0f";
    ctx.fillRect(0, 0, viewW, viewH);

    // Base cell size (fit map in view), then apply zoom
    const baseCell = Math.max(4, Math.floor(Math.min(viewW / mw, viewH / mh)));
    const cell = baseCell * zoom;
    const mapW = cell * mw;
    const mapH = cell * mh;

    // Center the map, then apply pan
    const ox = (viewW - mapW) / 2 + panX;
    const oy = (viewH - mapH) / 2 + panY;

    ctx.save();
    ctx.translate(ox, oy);

    // Background
    const bgImg = getImage(bgPath());
    if (bgImg) {
      const pat = ctx.createPattern(bgImg, "repeat");
      if (pat) {
        ctx.fillStyle = pat;
        ctx.fillRect(0, 0, mapW, mapH);
      }
    }

    // Map tiles
    for (let y = 0; y < mh; y++) {
      for (let x = 0; x < mw; x++) {
        const t = tiles[y]?.[x] ?? "empty";
        const sprite = tilePath(t);
        if (sprite) {
          const img = getImage(sprite);
          if (img) {
            ctx.drawImage(img, x * cell, y * cell, cell, cell);
            continue;
          }
        }
        if (t === "empty") continue;
        let fill = "#3e2c20";
        if (t === "ore_titanium") fill = "#455a64";
        if (t === "ore_axionite") fill = "#4a148c";
        ctx.fillStyle = fill;
        ctx.fillRect(x * cell, y * cell, cell, cell);
      }
    }

    // Death heatmap
    if (showDeathHeatmap) {
      const { death } = computeHeatmapOverlay(replay, roundIndex, trailRounds);
      let maxD = 1;
      for (const row of death) for (const v of row) maxD = Math.max(maxD, v);
      for (let y = 0; y < mh; y++) {
        for (let x = 0; x < mw; x++) {
          const v = death[y]?.[x] ?? 0;
          if (!v) continue;
          const a = 0.15 + (0.55 * v) / maxD;
          ctx.fillStyle = `rgba(255, 50, 50, ${a})`;
          ctx.fillRect(x * cell, y * cell, cell, cell);
        }
      }
    }

    // Movement trails
    if (showTrails) {
      const { trailsA, trailsB } = computeHeatmapOverlay(replay, roundIndex, trailRounds);
      const drawTrail = (pts: [number, number][], color: string) => {
        if (pts.length < 2) return;
        ctx.strokeStyle = color;
        ctx.lineWidth = Math.max(1, cell / 8);
        ctx.globalAlpha = 0.35;
        ctx.beginPath();
        ctx.moveTo(pts[0][0] * cell + cell / 2, pts[0][1] * cell + cell / 2);
        for (let i = 1; i < pts.length; i++) {
          ctx.lineTo(pts[i][0] * cell + cell / 2, pts[i][1] * cell + cell / 2);
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
      };
      if (teamFilter === "both" || teamFilter === "a") drawTrail(trailsA, "#4fc3f7");
      if (teamFilter === "both" || teamFilter === "b") drawTrail(trailsB, "#ff7043");
    }

    // Entities
    const all: ParsedEntity[] = [
      ...r.team_a.entities.map((e) => ({ ...e, team: "a" as const })),
      ...r.team_b.entities.map((e) => ({ ...e, team: "b" as const })),
    ];

    const drawList = all.sort((a, b) => {
      const order = (t: string) => {
        if (t === "road") return 0;
        if (t === "conveyor" || t === "armoured_conveyor" || t === "bridge" || t === "splitter") return 1;
        if (t === "barrier") return 2;
        if (t === "harvester" || t === "foundry") return 3;
        if (t === "core") return 4;
        if (t === "gunner" || t === "sentinel" || t === "breach" || t === "launcher") return 5;
        if (t === "builder_bot") return 6;
        return 3;
      };
      return order(a.type) - order(b.type);
    });

    const flowPhase = showConveyorFlow ? (Date.now() / 400) % 1 : 0;

    for (const e of drawList) {
      if (teamFilter !== "both" && e.team !== teamFilter) continue;
      ctx.globalAlpha = 1;
      const color = e.team === "a" ? "#4fc3f7" : "#ff7043";
      const imgSrc = spritePath(e.type, e.team, e.direction);
      const img = getImage(imgSrc);

      if (e.type === "core") {
        const [x0, y0] = e.position;
        const w = e.footprint_w ?? CORE_FOOTPRINT;
        const h = e.footprint_h ?? CORE_FOOTPRINT;
        if (img) {
          ctx.drawImage(img, x0 * cell, y0 * cell, w * cell, h * cell);
        } else {
          ctx.fillStyle = color;
          ctx.fillRect(x0 * cell + 1, y0 * cell + 1, w * cell - 2, h * cell - 2);
          ctx.strokeStyle = "#fff";
          ctx.lineWidth = 1;
          ctx.strokeRect(x0 * cell + 0.5, y0 * cell + 0.5, w * cell - 1, h * cell - 1);
        }
        const maxHp = MAX_HP.core;
        const hp = e.hp ?? maxHp;
        if (hp < maxHp) {
          const barY = (y0 + h) * cell + 1;
          const barW = w * cell;
          ctx.fillStyle = "#1a1a24";
          ctx.fillRect(x0 * cell, barY, barW, 3);
          ctx.fillStyle = hp > maxHp * 0.3 ? "#66bb6a" : "#ef5350";
          ctx.fillRect(x0 * cell, barY, barW * Math.min(1, hp / maxHp), 3);
        }
        continue;
      }

      const [x, y] = e.position;

      if (img) {
        const pad = e.type === "builder_bot" ? cell * 0.05 : 0;
        ctx.drawImage(img, x * cell + pad, y * cell + pad, cell - pad * 2, cell - pad * 2);
      } else {
        const cx = x * cell + cell / 2;
        const cy = y * cell + cell / 2;
        ctx.fillStyle = color;
        if (e.type === "barrier") {
          ctx.strokeStyle = color;
          ctx.lineWidth = Math.max(2, cell / 6);
          ctx.strokeRect(x * cell + 2, y * cell + 2, cell - 4, cell - 4);
        } else if (e.type === "conveyor" || e.type === "armoured_conveyor") {
          ctx.fillStyle = e.type === "armoured_conveyor" ? "#5c6bc0" : "#37474f";
          ctx.fillRect(x * cell + 2, y * cell + 2, cell - 4, cell - 4);
        } else if (e.type === "harvester") {
          ctx.beginPath();
          ctx.moveTo(cx, y * cell + 3);
          ctx.lineTo(x * cell + cell - 3, cy);
          ctx.lineTo(cx, y * cell + cell - 3);
          ctx.lineTo(x * cell + 3, cy);
          ctx.closePath();
          ctx.fill();
        } else if (e.type === "builder_bot") {
          ctx.beginPath();
          ctx.arc(cx, cy, Math.max(2, cell * 0.28), 0, Math.PI * 2);
          ctx.fill();
        } else if (e.type === "gunner" || e.type === "sentinel" || e.type === "breach") {
          const rad = dirToRad(e.direction);
          ctx.save();
          ctx.translate(cx, cy);
          ctx.rotate(rad);
          ctx.beginPath();
          ctx.moveTo(cell * 0.35, 0);
          ctx.lineTo(-cell * 0.2, cell * 0.22);
          ctx.lineTo(-cell * 0.2, -cell * 0.22);
          ctx.closePath();
          ctx.fill();
          ctx.restore();
        } else {
          ctx.fillRect(x * cell + 3, y * cell + 3, cell - 6, cell - 6);
        }
      }

      if (showConveyorFlow && (e.type === "conveyor" || e.type === "armoured_conveyor") && e.stored_resource) {
        const cx = x * cell + cell / 2;
        const cy = y * cell + cell / 2;
        const rad = dirToRad(e.direction);
        const t = flowPhase;
        const px = cx + Math.cos(rad) * cell * 0.25 * (t - 0.5) * 2;
        const py = cy + Math.sin(rad) * cell * 0.25 * (t - 0.5) * 2;
        ctx.fillStyle = "#fff59d";
        ctx.beginPath();
        ctx.arc(px, py, Math.max(1, cell / 10), 0, Math.PI * 2);
        ctx.fill();
      }

      if (e.hp !== undefined && e.type !== "core" && e.type !== "marker") {
        const maxHp = MAX_HP[e.type] ?? 30;
        if (e.hp < maxHp) {
          const barY = (y + 1) * cell - 2;
          const barW = cell - 2;
          ctx.fillStyle = "rgba(0,0,0,0.5)";
          ctx.fillRect(x * cell + 1, barY, barW, 2);
          ctx.fillStyle = e.hp > maxHp * 0.3 ? "#66bb6a" : "#ef5350";
          ctx.fillRect(x * cell + 1, barY, barW * Math.min(1, e.hp / maxHp), 2);
        }
      }
    }

    // Selection highlight
    if (selected && (teamFilter === "both" || selected.team === teamFilter)) {
      for (const [cx, cy] of entityCells(selected)) {
        ctx.strokeStyle = "#ffeb3b";
        ctx.lineWidth = 2;
        ctx.strokeRect(cx * cell + 1, cy * cell + 1, cell - 2, cell - 2);
      }
      if (showVision) {
        const vr2 = visionR2ForType(selected.type);
        if (vr2 !== null) {
          const [tcx, tcy] = centerOfEntity(selected);
          const radius = Math.sqrt(vr2) * cell;
          ctx.strokeStyle = "rgba(79, 195, 247, 0.35)";
          ctx.fillStyle = "rgba(79, 195, 247, 0.08)";
          ctx.beginPath();
          ctx.arc(tcx * cell, tcy * cell, radius, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }
      }
      if (showAttackRange) {
        const ar2 = attackR2ForType(selected.type);
        if (ar2 !== null) {
          const [tcx, tcy] = centerOfEntity(selected);
          const radius = Math.sqrt(ar2) * cell;
          ctx.strokeStyle = "rgba(255, 112, 67, 0.45)";
          ctx.fillStyle = "rgba(255, 112, 67, 0.06)";
          ctx.beginPath();
          ctx.arc(tcx * cell, tcy * cell, radius, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
        }
      }
    }

    ctx.restore();

    // Zoom indicator (top-right)
    if (zoom !== 1) {
      ctx.fillStyle = "rgba(0,0,0,0.5)";
      ctx.fillRect(viewW - 60, 4, 56, 18);
      ctx.fillStyle = "#c8c8d8";
      ctx.font = "11px var(--font-geist-mono, monospace)";
      ctx.textAlign = "right";
      ctx.fillText(`${zoom.toFixed(1)}x`, viewW - 8, 17);
      ctx.textAlign = "start";
    }
  }, [
    replay, roundIndex, teamFilter, selected, showTrails,
    showDeathHeatmap, showVision, showAttackRange, showConveyorFlow,
    trailRounds, r, mw, mh, tiles, zoom, panX, panY,
  ]);

  // Sprite loading poller
  useEffect(() => {
    let mounted = true;
    let attempts = 0;
    const check = () => {
      if (!mounted || attempts > 20) return;
      attempts++;
      let allLoaded = true;
      for (const [, img] of imageCache) {
        if (!img.complete) { allLoaded = false; break; }
      }
      if (allLoaded && imageCache.size > 0) redraw();
      else setTimeout(check, 150);
    };
    check();
    return () => { mounted = false; };
  }, [redraw]);

  useEffect(() => { redraw(); }, [redraw]);

  useEffect(() => {
    if (!showConveyorFlow) return;
    let id: number;
    const tick = () => { redraw(); id = requestAnimationFrame(tick); };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [showConveyorFlow, redraw]);

  // Wheel zoom — zoom toward cursor position
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      const b = canvas.getBoundingClientRect();
      const cursorX = ev.clientX - b.left;
      const cursorY = ev.clientY - b.top;

      const oldZoom = zoom;
      const delta = ev.deltaY > 0 ? -0.15 : 0.15;
      const newZoom = Math.min(8, Math.max(0.5, oldZoom + delta * oldZoom));
      const scale = newZoom / oldZoom;

      // Adjust pan so zoom centers on cursor
      const viewW = b.width;
      const viewH = b.height;
      const baseCell = Math.max(4, Math.floor(Math.min(viewW / mw, viewH / mh)));
      const oldMapW = baseCell * oldZoom * mw;
      const oldMapH = baseCell * oldZoom * mh;
      const oldOx = (viewW - oldMapW) / 2 + panX;
      const oldOy = (viewH - oldMapH) / 2 + panY;

      const mapCursorX = cursorX - oldOx;
      const mapCursorY = cursorY - oldOy;

      const newMapCursorX = mapCursorX * scale;
      const newMapCursorY = mapCursorY * scale;

      const newMapW = baseCell * newZoom * mw;
      const newMapH = baseCell * newZoom * mh;
      const newOxBase = (viewW - newMapW) / 2;
      const newOyBase = (viewH - newMapH) / 2;

      setPanX(cursorX - newMapCursorX - newOxBase);
      setPanY(cursorY - newMapCursorY - newOyBase);
      setZoom(newZoom);
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [zoom, panX, panY, mw, mh]);

  // Convert screen coords to grid coords
  const screenToGrid = useCallback((clientX: number, clientY: number): [number, number] | null => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const b = canvas.getBoundingClientRect();
    const viewW = b.width;
    const viewH = b.height;
    const baseCell = Math.max(4, Math.floor(Math.min(viewW / mw, viewH / mh)));
    const cell = baseCell * zoom;
    const ox = (viewW - cell * mw) / 2 + panX;
    const oy = (viewH - cell * mh) / 2 + panY;

    const mapX = (clientX - b.left - ox) / cell;
    const mapY = (clientY - b.top - oy) / cell;
    return [Math.floor(mapX), Math.floor(mapY)];
  }, [zoom, panX, panY, mw, mh]);

  const hitTest = useCallback((clientX: number, clientY: number) => {
    const pos = screenToGrid(clientX, clientY);
    if (!pos) return null;
    const [gx, gy] = pos;
    const all: ParsedEntity[] = [...r.team_a.entities, ...r.team_b.entities];
    const filtered = all.filter((e) => teamFilter === "both" || e.team === teamFilter);
    for (let i = filtered.length - 1; i >= 0; i--) {
      const e = filtered[i];
      for (const [cx, cy] of entityCells(e)) {
        if (cx === gx && cy === gy) return e;
      }
    }
    return null;
  }, [r, teamFilter, screenToGrid]);

  // Mouse handlers for panning
  const onMouseDown = useCallback((ev: React.MouseEvent) => {
    if (ev.button === 1 || (ev.button === 0 && ev.shiftKey)) {
      ev.preventDefault();
      dragRef.current = { startX: ev.clientX, startY: ev.clientY, panX0: panX, panY0: panY };
    }
  }, [panX, panY]);

  const onMouseMove = useCallback((ev: React.MouseEvent) => {
    if (!dragRef.current) return;
    const dx = ev.clientX - dragRef.current.startX;
    const dy = ev.clientY - dragRef.current.startY;
    setPanX(dragRef.current.panX0 + dx);
    setPanY(dragRef.current.panY0 + dy);
  }, []);

  const onMouseUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  const onClick = useCallback((ev: React.MouseEvent) => {
    if (dragRef.current) return;
    const hit = hitTest(ev.clientX, ev.clientY);
    onSelect(hit);
  }, [hitTest, onSelect]);

  const resetZoom = useCallback(() => {
    setZoom(1);
    setPanX(0);
    setPanY(0);
  }, []);

  return (
    <div className="flex flex-col gap-1">
      <div
        ref={wrapRef}
        className="relative w-full overflow-hidden rounded border border-[#2a2a38] bg-[#0a0a0f]"
        style={{ height: "clamp(320px, 60vh, 800px)" }}
      >
        <canvas
          ref={canvasRef}
          className="block cursor-crosshair"
          style={{ imageRendering: "auto", width: "100%", height: "100%" }}
          onClick={onClick}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        />
      </div>
      <div className="flex items-center gap-2 font-data text-[10px] text-[#6a6a7a]">
        <span>Scroll to zoom, Shift+drag to pan.</span>
        {zoom !== 1 && (
          <button
            type="button"
            onClick={resetZoom}
            className="rounded border border-[#2a2a38] px-1.5 py-0.5 text-[#8a8a9a] hover:bg-[#1a1a24]"
          >
            Reset zoom
          </button>
        )}
      </div>
    </div>
  );
}
