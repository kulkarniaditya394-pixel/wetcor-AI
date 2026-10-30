"use client";

import { Download, Play, Printer } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, form, type Metric } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { fmtNum, unit } from "@/lib/format";
import { CorrosionPlots, type RunData } from "./CorrosionPlots";
import { Alert, Badge, Button, Card, Field, LabeledInput, OriginBadge, Select, Spinner, Table } from "./ui";

type Method = "ocp" | "lpr" | "pdp" | "eis";
type Analysis = { status: string; metrics: Metric[]; warnings: string[]; notes: string[]; fit?: Record<string, unknown> };
type Quick = { method: Method; n_points: number; import_warnings: string[]; area_cm2: number | null; run: RunData; analysis: Analysis };
type MaterialProfile = { key: string; label: string; equivalent_weight_g_eq: number; density_g_cm3: number; source: string };

export type QuickInput = { file: File; method: Method; mapping: Record<string, string>; units: Record<string, string | null>; imag: "as_is" | "negated"; anodicNeg: boolean; area: string; reference: string };

const KEY = ["i_corr", "corrosion_rate", "rp", "e_corr_tafel", "e_corr_zero_current", "ocp_mean", "ocp_drift", "z_mod_low_f"];
const num = (s: string | undefined) => (s === undefined || s.trim() === "" ? undefined : Number(s));

/** Analyse an export without storing anything: parameters, key results, full metric table and plots. */
export function QuickAnalysis({ input }: { input: QuickInput }) {
  const materials = useApi<MaterialProfile[]>("/api/materials");
  const [p, setP] = useState<Record<string, string>>({});
  const [mat, setMat] = useState({ profile: "", ew: "", rho: "", source: "", alloy: false });
  const [res, setRes] = useState<Quick | null>(null);
  const [busy, setBusy] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const started = useRef(false);

  const buildParams = (q: Record<string, string>) => {
    const out: Record<string, unknown> = {};
    if (input.method === "ocp") Object.assign(out, { t_start_s: num(q.t_start_s), t_end_s: num(q.t_end_s) });
    if (input.method === "lpr") Object.assign(out, { e_corr_V: num(q.e_corr_V), half_window_mV: num(q.half_window_mV), stern_geary_B_V: num(q.stern_geary_B_V),
      beta_a_V_dec: num(q.beta_a_V_dec), beta_c_V_dec: num(q.beta_c_V_dec), B_source: q.B_source || undefined });
    if (input.method === "pdp" && q.anodic_lo && q.anodic_hi && q.cathodic_lo && q.cathodic_hi)
      Object.assign(out, { anodic_mV: [Number(q.anodic_lo), Number(q.anodic_hi)], cathodic_mV: [Number(q.cathodic_lo), Number(q.cathodic_hi)] });
    return Object.fromEntries(Object.entries(out).filter(([, v]) => v !== undefined && !(typeof v === "number" && Number.isNaN(v))));
  };
  const material = () => {
    if (mat.profile) return { profile: mat.profile };
    if (!mat.ew && !mat.rho) return null;
    return { equivalent_weight_g_eq: num(mat.ew) ?? null, density_g_cm3: num(mat.rho) ?? null, source: mat.source || null, is_alloy: mat.alloy };
  };

  const run = async (q: Record<string, string> = p) => {
    setBusy(true);
    setErr(null);
    try {
      const meta = { method: input.method, mapping: Object.fromEntries(Object.entries(input.mapping).filter(([, c]) => c)), units: input.units, imag_convention: input.imag,
        anodic_negative: input.anodicNeg, exposed_area_cm2: input.area ? Number(input.area) : null, reference_electrode: input.reference || null };
      setRes(await api<Quick>("/api/corrosion/quick", { method: "POST", body: form({ file: [input.file, input.file.name], meta: JSON.stringify(meta), params: JSON.stringify(buildParams(q)),
        material: JSON.stringify(material()) }) }));
    } catch (e) {
      setErr((e as Error).message);
      setRes(null);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    run();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const inp = (k: string, label: string, hint?: string, type = "number") => (
    <LabeledInput key={k} label={label} hint={hint} type={type} step="any" value={p[k] ?? ""} onChange={(e) => setP({ ...p, [k]: e.target.value })} />
  );
  const a = res?.analysis;
  const proposal = a?.fit?.proposal as { anodic: number[] | null; cathodic: number[] | null } | undefined;
  const key = (a?.metrics ?? []).filter((m) => KEY.includes(m.name)).sort((x, y) => KEY.indexOf(x.name) - KEY.indexOf(y.name)).slice(0, 4);
  const tone = a?.status === "ok" ? "good" : a?.status === "invalid" ? "bad" : "warn";

  const csv = () => {
    if (!a) return;
    const rows = [["quantity", "value", "unit", "origin", "formula", "valid"], ...a.metrics.map((m) => [m.label, String(m.value ?? ""), m.unit, m.origin, m.formula, String(m.valid)])];
    const text = rows.map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(",")).join("\n");
    const el = document.createElement("a");
    el.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
    el.download = `wetcor_${input.method}_results.csv`;
    el.click();
    URL.revokeObjectURL(el.href);
  };

  return (
    <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]" id="quick-analysis">
      <div className="flex min-w-0 flex-col gap-5">
        <Card title={`Results · ${input.method.toUpperCase()}`} actions={a && <Badge tone={tone}>{a.status}</Badge>}>
          {busy && !res ? <Spinner label="Analysing in your browser" /> : err ? <Alert tone="bad" title="Analysis refused">{err}</Alert> : res && a && (
            <div className="flex flex-col gap-4">
              {key.length > 0 && (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {key.map((m) => (
                    <div key={m.name} className="rounded-lg border border-line bg-panel-2 px-3 py-2.5">
                      <div className="text-[11px] uppercase tracking-wider text-muted">{m.label}</div>
                      <div className="num mt-1 text-xl font-semibold text-ink">{fmtNum(m.value)} <span className="text-sm font-normal text-ink-2">{unit(m.unit)}</span></div>
                      <div className="mt-1.5 flex items-center gap-1.5"><OriginBadge origin={m.origin} />{!m.valid && <Badge tone="bad">unreliable</Badge>}</div>
                    </div>
                  ))}
                </div>
              )}
              {res.import_warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
              {a.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
              {a.notes.map((n) => <Alert key={n} tone="info">{n}</Alert>)}
              <CorrosionPlots run={res.run} fit={a.fit} />
              <Table head={["Quantity", "Value", "Unit", "Origin", "Formula", "Status"]}>
                {a.metrics.map((m) => (
                  <tr key={m.name}>
                    <td className="min-w-56 whitespace-normal! text-ink">{m.label}
                      {(m.assumptions.length > 0 || Object.keys(m.parameters).length > 0) && (
                        <details className="mt-1 text-xs text-muted"><summary className="cursor-pointer">parameters &amp; assumptions</summary>
                          <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{JSON.stringify(m.parameters, null, 1)}</pre>
                          <ul className="list-disc pl-4">{m.assumptions.map((x) => <li key={x}>{x}</li>)}</ul>
                        </details>)}
                    </td>
                    <td className="num font-semibold">{fmtNum(m.value)}</td><td>{unit(m.unit)}</td><td><OriginBadge origin={m.origin} /></td>
                    <td className="min-w-48 whitespace-normal! font-mono text-[11px] text-ink-2">{m.formula}</td>
                    <td>{m.valid ? <Badge tone="good">valid</Badge> : <Badge tone="bad" title={m.warnings.join(" ")}>unreliable</Badge>}</td>
                  </tr>
                ))}
              </Table>
              <div className="flex flex-wrap gap-2 print:hidden">
                <Button icon={<Download className="size-4" />} onClick={csv}>Download results (CSV)</Button>
                <Button variant="ghost" icon={<Printer className="size-4" />} onClick={() => window.print()}>Print / save as PDF</Button>
              </div>
              <p className="text-xs text-muted">Calculated in your browser from the mapped file; nothing is stored or uploaded. {res.n_points} data points analysed.</p>
            </div>
          )}
        </Card>
      </div>
      <div className="flex min-w-0 flex-col gap-5 print:hidden">
        <Card title="Analysis parameters">
          <div className="flex flex-col gap-3">
            {input.method === "ocp" && <div className="grid grid-cols-2 gap-3">{inp("t_start_s", "Interval start (s)", "Blank = final 20 %")}{inp("t_end_s", "Interval end (s)")}</div>}
            {input.method === "lpr" && (
              <>
                <div className="grid grid-cols-2 gap-3">{inp("e_corr_V", "E_corr override (V)", "Blank = zero-current crossing")}{inp("half_window_mV", "Half-window (mV)", "Default ±10 mV")}</div>
                <div className="rounded-md border border-line p-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Stern–Geary coefficient (optional)</div>
                  <div className="grid grid-cols-3 gap-2">{inp("stern_geary_B_V", "B (V)")}{inp("beta_a_V_dec", "β_a (V/dec)")}{inp("beta_c_V_dec", "β_c (V/dec)")}</div>
                  <div className="mt-2">{inp("B_source", "Source of B / Tafel slopes", "Required for i_corr", "text")}</div>
                </div>
              </>
            )}
            {input.method === "pdp" && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  {inp("anodic_lo", "Anodic from (mV above E_corr)")}{inp("anodic_hi", "Anodic to (mV)")}
                  {inp("cathodic_lo", "Cathodic from (mV below E_corr)")}{inp("cathodic_hi", "Cathodic to (mV)")}
                </div>
                {proposal?.anodic && proposal?.cathodic && (
                  <Button size="sm" onClick={() => {
                    const q = { ...p, anodic_lo: String(proposal.anodic![0]), anodic_hi: String(proposal.anodic![1]), cathodic_lo: String(proposal.cathodic![0]), cathodic_hi: String(proposal.cathodic![1]) };
                    setP(q);
                    run(q);
                  }}>Confirm proposed regions ({proposal.anodic.join("–")} / {proposal.cathodic.join("–")} mV)</Button>
                )}
                <p className="text-xs text-muted">With no regions entered, WETCOR proposes the best linear Tafel windows and flags the result for your review. Confirming them (or entering your own) makes it a reviewed result.</p>
              </>
            )}
            {input.method === "eis" && <p className="text-sm text-muted">EIS needs no parameters: Nyquist and Bode plots plus descriptors. No corrosion rate is derived from EIS.</p>}
            {(input.method === "lpr" || input.method === "pdp") && (
              <div className="rounded-md border border-line p-3">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Material properties for corrosion rate (optional)</div>
                <Field label="Reference profile">
                  <Select aria-label="Material profile" value={mat.profile} onChange={(e) => setMat({ ...mat, profile: e.target.value })}>
                    <option value="">Custom values / none</option>
                    {(materials.data ?? []).map((m) => <option key={m.key} value={m.key}>{m.label} — EW {m.equivalent_weight_g_eq}, ρ {m.density_g_cm3}</option>)}
                  </Select>
                </Field>
                {!mat.profile && (
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <LabeledInput label="EW (g/eq)" type="number" step="any" value={mat.ew} onChange={(e) => setMat({ ...mat, ew: e.target.value })} />
                    <LabeledInput label="Density (g/cm³)" type="number" step="any" value={mat.rho} onChange={(e) => setMat({ ...mat, rho: e.target.value })} />
                    <div className="col-span-2"><LabeledInput label="Source of EW and density" value={mat.source} onChange={(e) => setMat({ ...mat, source: e.target.value })} placeholder="e.g. ASTM G102, supplier certificate" /></div>
                    <label className="col-span-2 flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={mat.alloy} onChange={(e) => setMat({ ...mat, alloy: e.target.checked })} className="accent-[var(--color-accent)]" />Alloy (EW depends on composition)</label>
                  </div>
                )}
                {mat.profile && <p className="mt-2 text-xs text-muted">{materials.data?.find((m) => m.key === mat.profile)?.source}</p>}
              </div>
            )}
            <Button variant="primary" icon={<Play className="size-4" />} busy={busy} onClick={() => run()}>Re-analyse</Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
