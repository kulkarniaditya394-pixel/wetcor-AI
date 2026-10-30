"use client";

import { useMemo } from "react";
import { Plot, type Trace } from "./Plot";

export type RunData = { method: string; n_points: number; data: Record<string, (number | null)[] | number> };
type Fit = Record<string, unknown> | undefined;

/** Log-axis range from the 1st percentile of |i| so one near-zero sample at E_corr cannot stretch the axis. */
function logRange(v: (number | null)[]): [number, number] | undefined {
  const logs = v.filter((x): x is number => x != null && x > 0).map(Math.log10).sort((a, b) => a - b);
  if (!logs.length) return undefined;
  return [logs[Math.floor(0.01 * logs.length)] - 0.5, logs[logs.length - 1] + 0.3];
}

const col = (d: RunData, k: string) => (d.data[k] as (number | null)[] | undefined) ?? [];

/** Plots of the processed (canonical-unit) run data plus the current analysis overlay. */
export function CorrosionPlots({ run, fit, demo }: { run: RunData; fit?: Fit; demo?: boolean }) {
  const tag = demo ? " — DEMO SYNTHETIC" : "";
  const plots = useMemo(() => {
    const out: { key: string; label: string; data: Trace[]; layout: Record<string, unknown> }[] = [];
    if (run.method === "ocp") {
      const t = col(run, "time_s"), e = col(run, "potential_V");
      const iv = fit?.interval as { t_start_s: number; t_end_s: number } | undefined;
      out.push({ key: "ocp", label: "Open-circuit potential versus time", data: [{ x: t, y: e, type: "scattergl", mode: "lines", name: "E (measured)", line: { width: 1.5 } }],
        layout: { title: { text: "OCP" + tag, font: { size: 13 } }, xaxis: { title: { text: "Time (s)" } }, yaxis: { title: { text: "E (V vs ref.)" } },
          shapes: iv ? [{ type: "rect", xref: "x", yref: "paper", x0: iv.t_start_s, x1: iv.t_end_s, y0: 0, y1: 1, fillcolor: "rgba(47,184,198,0.12)", line: { width: 0 } }] : [] } });
    }
    if (run.method === "lpr") {
      const i = col(run, "current_density_A_cm2").map((v) => (v == null ? null : v * 1e6)), e = col(run, "potential_V");
      const line = fit?.line as { i: number[]; e: number[] } | undefined;
      const w = fit?.window as { e_low_V: number; e_high_V: number } | undefined;
      const data: Trace[] = [{ x: i, y: e, type: "scattergl", mode: "markers", marker: { size: 3 }, name: "data" }];
      if (line) data.push({ x: line.i.map((v) => v * 1e6), y: line.e, mode: "lines", name: "linear fit (R_p)", line: { color: "#f06363", width: 2 } });
      out.push({ key: "lpr", label: "Linear polarisation: potential versus current density", data,
        layout: { title: { text: "Linear polarisation" + tag, font: { size: 13 } }, xaxis: { title: { text: "i (µA/cm²)" } }, yaxis: { title: { text: "E (V vs ref.)" } },
          shapes: w ? [{ type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: w.e_low_V, y1: w.e_high_V, fillcolor: "rgba(47,184,198,0.10)", line: { width: 0 } }] : [] } });
    }
    if (run.method === "pdp") {
      const i = col(run, "current_density_A_cm2"), e = col(run, "potential_V");
      const absI = i.map((v) => (v == null || v === 0 ? null : Math.abs(v)));
      const anodic = i.map((v, k) => (v != null && v > 0 ? e[k] : null));
      const cathodic = i.map((v, k) => (v != null && v < 0 ? e[k] : null));
      const data: Trace[] = [
        { x: absI, y: anodic, type: "scattergl", mode: "lines", name: "anodic (i > 0)", line: { width: 1.5, color: "#2fb8c6" } },
        { x: absI, y: cathodic, type: "scattergl", mode: "lines", name: "cathodic (i < 0)", line: { width: 1.5, color: "#6aa8ff" } },
      ];
      const lines = fit?.lines as Record<string, { slope_V_dec: number; intercept_V: number; log_i_range: number[] }> | undefined;
      const shapes: Record<string, unknown>[] = [];
      for (const [b, c] of [["anodic", "#f06363"], ["cathodic", "#f2a93b"]] as const) {
        const ln = lines?.[b];
        if (ln) {
          const xs = [ln.log_i_range[0] - 1.5, ln.log_i_range[1]];
          data.push({ x: xs.map((x) => 10 ** x), y: xs.map((x) => ln.intercept_V + ln.slope_V_dec * x), mode: "lines", name: `${b} Tafel fit`, line: { dash: "dash", color: c, width: 2 } });
        }
        const reg = (fit?.regions as Record<string, number[] | null> | undefined)?.[b];
        const ec = fit?.e_corr_obs_V as number | undefined;
        if (reg && ec != null) {
          const [lo, hi] = reg.map((v) => v / 1000);
          shapes.push({ type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: b === "anodic" ? ec + lo : ec - hi, y1: b === "anodic" ? ec + hi : ec - lo, fillcolor: b === "anodic" ? "rgba(240,99,99,0.08)" : "rgba(242,169,59,0.08)", line: { width: 0 } });
        }
      }
      const pt = fit?.intersection as { log10_i: number; e_V: number } | undefined;
      if (pt) data.push({ x: [10 ** pt.log10_i], y: [pt.e_V], mode: "markers", name: "i_corr / E_corr (fit)", marker: { size: 9, color: "#e7edf6", symbol: "x" } });
      const excluded = run.data.log_excluded_zero as number | undefined;
      out.push({ key: "pdp", label: "Potentiodynamic polarisation: potential versus log absolute current density", data,
        layout: { title: { text: `Polarisation curve (|i|, semi-log)${tag}${excluded ? ` — ${excluded} zero-current point(s) omitted` : ""}`, font: { size: 13 } },
          xaxis: { title: { text: "|i| (A/cm²)" }, type: "log", range: logRange(absI) }, yaxis: { title: { text: "E (V vs ref.)" } }, shapes } });
    }
    if (run.method === "eis") {
      const zr = col(run, "z_real_ohm"), zi = col(run, "z_imag_ohm"), f = col(run, "frequency_Hz");
      const zm = col(run, "z_mod_calc_ohm"), ph = col(run, "phase_calc_deg");
      out.push({ key: "nyq", label: "Nyquist plot", data: [{ x: zr, y: zi.map((v) => (v == null ? null : -v)), mode: "lines+markers", marker: { size: 5 }, name: "−Z'' vs Z'", text: f.map((v) => `${v} Hz`) }],
        layout: { title: { text: "Nyquist" + tag, font: { size: 13 } }, xaxis: { title: { text: "Z' (Ω)" } }, yaxis: { title: { text: "−Z'' (Ω)" }, scaleanchor: "x", scaleratio: 1 } } });
      out.push({ key: "bode", label: "Bode plot: impedance magnitude and phase versus frequency", data: [
        { x: f, y: zm, mode: "lines+markers", marker: { size: 4 }, name: "|Z|" },
        { x: f, y: ph, mode: "lines+markers", marker: { size: 4 }, name: "phase", yaxis: "y2" },
      ], layout: { title: { text: "Bode" + tag, font: { size: 13 } }, xaxis: { title: { text: "f (Hz)" }, type: "log" }, yaxis: { title: { text: "|Z| (Ω)" }, type: "log" },
        yaxis2: { title: { text: "phase (°)" }, overlaying: "y", side: "right", gridcolor: "rgba(0,0,0,0)" } } });
    }
    return out;
  }, [run, fit, tag]);
  return (
    <div className={plots.length > 1 ? "grid gap-4 lg:grid-cols-2" : ""}>
      {plots.map((p) => <Plot key={p.key} data={p.data} layout={p.layout} label={p.label} filename={`wetcor_${p.key}`} height={380} />)}
    </div>
  );
}
