"use client";

import { useEffect, useRef } from "react";

/* Thin wrapper over plotly.js (loaded on demand in the browser only). */
export type Trace = Record<string, unknown>;

const BASE_LAYOUT = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "#0b1322",
  font: { family: "Segoe UI, system-ui, sans-serif", size: 12, color: "#b4c2d6" },
  margin: { l: 64, r: 18, t: 30, b: 50 },
  legend: { orientation: "h", y: -0.22, font: { size: 11 } },
  hoverlabel: { bgcolor: "#142035", bordercolor: "#2a3c5c", font: { color: "#e7edf6" } },
  colorway: ["#2fb8c6", "#f2a93b", "#6aa8ff", "#f06363", "#43c08f", "#b388ff"],
};
const AXIS = { gridcolor: "#1f2d47", zerolinecolor: "#2a3c5c", linecolor: "#2a3c5c", ticks: "outside", tickcolor: "#2a3c5c", exponentformat: "power" };

function withAxes(layout: Record<string, unknown>) {
  const out: Record<string, unknown> = { ...BASE_LAYOUT, ...layout };
  for (const key of Object.keys(out)) {
    if (/^[xy]axis\d*$/.test(key)) out[key] = { ...AXIS, ...(out[key] as object) };
  }
  for (const k of ["xaxis", "yaxis"]) if (!out[k]) out[k] = AXIS;
  return out;
}

export function Plot({ data, layout = {}, height = 360, label, filename = "wetcor-plot" }: { data: Trace[]; layout?: Record<string, unknown>; height?: number; label: string; filename?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    let cancelled = false;
    import("plotly.js-dist-min").then(({ default: Plotly }) => {
      if (cancelled || !el) return;
      Plotly.react(el, data, withAxes(layout), {
        displaylogo: false,
        responsive: true,
        modeBarButtonsToRemove: ["lasso2d", "select2d"],
        toImageButtonOptions: { format: "png", filename, scale: 2 },
      });
    });
    return () => {
      cancelled = true;
    };
  }, [data, layout, filename]);

  useEffect(() => {
    const el = ref.current;
    return () => {
      if (el) import("plotly.js-dist-min").then(({ default: Plotly }) => Plotly.purge(el));
    };
  }, []);

  return <div ref={ref} style={{ height }} role="img" aria-label={label} className="w-full" />;
}
