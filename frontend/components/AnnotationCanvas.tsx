"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import type { CAGeometry, Pt } from "@/lib/api";

export type Handles = { baseline: [Pt, Pt]; contact_left?: Pt; contact_right?: Pt; tangent_left?: Pt; tangent_right?: Pt };
type Key = "b1" | "b2" | "cl" | "cr" | "tl" | "tr";

const HANDLE_META: Record<Key, { label: string; color: string }> = {
  b1: { label: "Baseline point 1", color: "#2fb8c6" },
  b2: { label: "Baseline point 2", color: "#2fb8c6" },
  cl: { label: "Left contact point", color: "#f2a93b" },
  cr: { label: "Right contact point", color: "#f2a93b" },
  tl: { label: "Left tangent point", color: "#b388ff" },
  tr: { label: "Right tangent point", color: "#b388ff" },
};

function get(h: Handles, k: Key): Pt | undefined {
  return { b1: h.baseline[0], b2: h.baseline[1], cl: h.contact_left, cr: h.contact_right, tl: h.tangent_left, tr: h.tangent_right }[k];
}
function set(h: Handles, k: Key, p: Pt): Handles {
  if (k === "b1") return { ...h, baseline: [p, h.baseline[1]] };
  if (k === "b2") return { ...h, baseline: [h.baseline[0], p] };
  const field = { cl: "contact_left", cr: "contact_right", tl: "tangent_left", tr: "tangent_right" }[k] as keyof Handles;
  return { ...h, [field]: p };
}

/** Extend the line through a and b to the image's left and right edges. */
function extend(a: Pt, b: Pt, w: number): [Pt, Pt] {
  const dx = b[0] - a[0];
  if (Math.abs(dx) < 1e-9) return [a, b];
  const m = (b[1] - a[1]) / dx;
  return [[0, a[1] - m * a[0]], [w, a[1] + m * (w - a[0])]];
}

export function AnnotationCanvas({ src, width, height, geometry, handles, onHandlesChange, mode, roi, roiDrawing, onRoi, labels }: {
  src: string; width: number; height: number; geometry?: CAGeometry | null; handles: Handles | null; onHandlesChange?: (h: Handles) => void;
  mode: "auto" | "manual_tangent"; roi: [number, number, number, number] | null; roiDrawing: boolean; onRoi?: (r: [number, number, number, number] | null) => void;
  labels?: { left?: string; right?: string };
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<Key | null>(null);
  const [roiStart, setRoiStart] = useState<Pt | null>(null);
  const [roiLive, setRoiLive] = useState<[number, number, number, number] | null>(null);
  const [k, setK] = useState(1); // image px per screen px

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setK(width / Math.max(el.clientWidth, 1)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [width]);

  const toImg = (e: PointerEvent): Pt => {
    const r = svgRef.current!.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * width;
    const y = ((e.clientY - r.top) / r.height) * height;
    return [Math.min(Math.max(x, 0), width), Math.min(Math.max(y, 0), height)];
  };

  const keys: Key[] = ["b1", "b2", "cl", "cr", ...(mode === "manual_tangent" ? (["tl", "tr"] as Key[]) : [])];
  const onKey = (key: Key) => (e: KeyboardEvent) => {
    if (!handles || !onHandlesChange) return;
    const step = e.shiftKey ? 10 : 1;
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    const p = get(handles, key);
    if (!d || !p) return;
    e.preventDefault();
    onHandlesChange(set(handles, key, [p[0] + d[0], p[1] + d[1]]));
  };

  const r = 7 * k;
  const sw = { vectorEffect: "non-scaling-stroke" as const };
  const shownRoi = roiLive ?? roi;
  const base = handles?.baseline ?? (geometry?.baseline as [Pt, Pt] | undefined);
  const tangents: [Pt | undefined, Pt | undefined][] =
    mode === "manual_tangent" && handles
      ? [[handles.contact_left, handles.tangent_left], [handles.contact_right, handles.tangent_right]]
      : [[geometry?.tangent_left?.[0], geometry?.tangent_left?.[1]], [geometry?.tangent_right?.[0], geometry?.tangent_right?.[1]]];

  return (
    <div className="relative w-full select-none overflow-hidden rounded-md border border-line bg-black">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt="Captured droplet image under analysis" width={width} height={height} className="block h-auto w-full" draggable={false} />
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        className={`absolute inset-0 h-full w-full ${roiDrawing ? "cursor-crosshair" : ""}`}
        onPointerDown={(e) => {
          if (!roiDrawing) return;
          (e.target as Element).setPointerCapture?.(e.pointerId);
          setRoiStart(toImg(e));
        }}
        onPointerMove={(e) => {
          if (drag && handles && onHandlesChange) onHandlesChange(set(handles, drag, toImg(e)));
          else if (roiStart) {
            const p = toImg(e);
            setRoiLive([Math.min(p[0], roiStart[0]), Math.min(p[1], roiStart[1]), Math.abs(p[0] - roiStart[0]), Math.abs(p[1] - roiStart[1])]);
          }
        }}
        onPointerUp={() => {
          setDrag(null);
          if (roiStart && roiLive && onRoi) onRoi(roiLive[2] > 32 && roiLive[3] > 32 ? (roiLive.map(Math.round) as [number, number, number, number]) : null);
          setRoiStart(null);
          setRoiLive(null);
        }}
      >
        {shownRoi && <rect x={shownRoi[0]} y={shownRoi[1]} width={shownRoi[2]} height={shownRoi[3]} fill="rgba(47,184,198,0.06)" stroke="#e7edf6" strokeDasharray="6 4" strokeWidth={1.2} {...sw} />}
        {geometry?.contour && <polyline points={geometry.contour.map((p) => p.join(",")).join(" ")} fill="none" stroke="#43c08f" strokeWidth={1.6} {...sw} />}
        {geometry?.circle && <circle cx={geometry.circle.centre[0]} cy={geometry.circle.centre[1]} r={geometry.circle.radius} fill="none" stroke="#d07cf0" strokeDasharray="5 5" strokeWidth={1} {...sw} />}
        {base && (() => {
          const [a, b] = extend(base[0], base[1], width);
          return <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#2fb8c6" strokeWidth={1.6} {...sw} />;
        })()}
        {tangents.map(([c, t], i) =>
          c && t ? <line key={i} x1={c[0]} y1={c[1]} x2={c[0] + (t[0] - c[0]) * 1.6} y2={c[1] + (t[1] - c[1]) * 1.6} stroke="#f2a93b" strokeWidth={1.6} {...sw} /> : null,
        )}
        {labels?.left && geometry?.contact_left && (
          <text x={geometry.contact_left[0] - 12 * k} y={geometry.contact_left[1] - 14 * k} textAnchor="end" fontSize={13 * k} fill="#f2a93b" stroke="#000" strokeWidth={3 * k} paintOrder="stroke">{labels.left}</text>
        )}
        {labels?.right && geometry?.contact_right && (
          <text x={geometry.contact_right[0] + 12 * k} y={geometry.contact_right[1] - 14 * k} fontSize={13 * k} fill="#f2a93b" stroke="#000" strokeWidth={3 * k} paintOrder="stroke">{labels.right}</text>
        )}
        {handles && onHandlesChange && !roiDrawing &&
          keys.map((key) => {
            const p = get(handles, key);
            if (!p) return null;
            const m = HANDLE_META[key];
            return (
              <g key={key}>
                <circle cx={p[0]} cy={p[1]} r={r * 2.2} fill="transparent" className="cursor-grab"
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    (e.target as Element).setPointerCapture?.(e.pointerId);
                    setDrag(key);
                  }} />
                <circle
                  cx={p[0]} cy={p[1]} r={r} fill="rgba(0,0,0,0.35)" stroke={m.color} strokeWidth={2} {...sw}
                  tabIndex={0} role="button" aria-label={`${m.label} at x ${p[0].toFixed(0)}, y ${p[1].toFixed(0)}. Arrow keys move 1 px, Shift+Arrow 10 px.`}
                  className="cursor-grab outline-none focus:stroke-white"
                  onKeyDown={onKey(key)}
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    (e.target as Element).setPointerCapture?.(e.pointerId);
                    setDrag(key);
                  }}
                />
                <circle cx={p[0]} cy={p[1]} r={1.5 * k} fill={m.color} pointerEvents="none" />
              </g>
            );
          })}
      </svg>
    </div>
  );
}
