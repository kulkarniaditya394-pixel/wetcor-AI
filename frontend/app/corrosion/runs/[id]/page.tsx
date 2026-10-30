"use client";

import { Download, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CorrosionPlots, type RunData } from "@/components/CorrosionPlots";
import { Alert, Badge, Button, Card, DemoBanner, Field, KV, LabeledInput, OriginBadge, PageHeader, Select, Spinner, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, apiUrl, type AuditItem, type CorrosionRun, type Metric } from "@/lib/api";
import { fmtDate, fmtNum, unit } from "@/lib/format";

type Analysis = { analysis_id: number; status: string; params: Record<string, unknown>; fit?: Record<string, unknown>; warnings: string[]; notes: string[]; material?: Record<string, unknown> };
type Detail = CorrosionRun & {
  raw_file: { id: number; original_filename: string; sha256: string; size_bytes: number; integrity: string };
  current_analysis: Analysis | null; analyses: { id: number; status: string; params: Record<string, unknown>; superseded: boolean; created_at: string }[];
  metrics: Metric[]; history: AuditItem[];
};
type MaterialProfile = { key: string; label: string; equivalent_weight_g_eq: number; density_g_cm3: number; source: string };
const LABEL = { ocp: "Open-circuit potential", lpr: "Linear polarisation resistance", pdp: "Potentiodynamic polarisation", eis: "Electrochemical impedance spectroscopy" };

const num = (s: string) => (s.trim() === "" ? undefined : Number(s));

export default function RunPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const det = useApi<Detail>(`/api/corrosion/runs/${id}`);
  const data = useApi<RunData>(`/api/corrosion/runs/${id}/data`);
  const materials = useApi<MaterialProfile[]>("/api/materials");
  const [p, setP] = useState<Record<string, string>>({});
  const [mat, setMat] = useState({ profile: "", ew: "", rho: "", source: "", alloy: false });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const r = det.data;

  useEffect(() => {
    const prev = r?.current_analysis?.params as Record<string, unknown> | undefined;
    if (!prev) return;
    const flat: Record<string, string> = {};
    for (const [k, v] of Object.entries(prev)) {
      if (Array.isArray(v)) { flat[`${k}_lo`] = String(v[0]); flat[`${k}_hi`] = String(v[1]); } else if (v != null) flat[k] = String(v);
    }
    setP(flat);
  }, [r?.current_analysis?.analysis_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (det.loading && !r) return <Spinner />;
  if (det.error || !r) return <Alert tone="bad" title="Could not load run">{det.error}</Alert>;
  const fit = r.current_analysis?.fit;
  const proposal = fit?.proposal as { anodic: number[] | null; cathodic: number[] | null } | undefined;

  const buildParams = () => {
    const out: Record<string, unknown> = {};
    if (r.method === "ocp") Object.assign(out, { t_start_s: num(p.t_start_s ?? ""), t_end_s: num(p.t_end_s ?? "") });
    if (r.method === "lpr") Object.assign(out, { e_corr_V: num(p.e_corr_V ?? ""), half_window_mV: num(p.half_window_mV ?? ""), stern_geary_B_V: num(p.stern_geary_B_V ?? ""),
      beta_a_V_dec: num(p.beta_a_V_dec ?? ""), beta_c_V_dec: num(p.beta_c_V_dec ?? ""), B_source: p.B_source || undefined });
    if (r.method === "pdp" && p.anodic_mV_lo && p.anodic_mV_hi && p.cathodic_mV_lo && p.cathodic_mV_hi)
      Object.assign(out, { anodic_mV: [Number(p.anodic_mV_lo), Number(p.anodic_mV_hi)], cathodic_mV: [Number(p.cathodic_mV_lo), Number(p.cathodic_mV_hi)] });
    return Object.fromEntries(Object.entries(out).filter(([, v]) => v !== undefined && !(typeof v === "number" && Number.isNaN(v))));
  };
  const material = () => {
    if (mat.profile) return { profile: mat.profile };
    if (!mat.ew && !mat.rho) return null;
    return { equivalent_weight_g_eq: num(mat.ew) ?? null, density_g_cm3: num(mat.rho) ?? null, source: mat.source || null, is_alloy: mat.alloy };
  };
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api(`/api/corrosion/runs/${id}/analyze`, { method: "POST", json: { params: buildParams(), material: material() } });
      det.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const inp = (k: string, label: string, hint?: string, type = "number") => (
    <LabeledInput key={k} label={label} hint={hint} type={type} step="any" value={p[k] ?? ""} onChange={(e) => setP({ ...p, [k]: e.target.value })} />
  );
  const statusTone = r.analysis_status === "analysed" ? "good" : r.analysis_status === "imported" ? "neutral" : r.analysis_status === "analysis_invalid" ? "bad" : "warn";

  return (
    <>
      <PageHeader eyebrow="Corrosion Lab · Run" title={`EC-${r.id} · ${LABEL[r.method]}`}
        subtitle={<>Specimen <Link className="text-accent hover:underline" href={`/experiments/specimens/${r.specimen_id}`}>#{r.specimen_id}</Link>{r.experiment_id && <> · Experiment <Link className="text-accent hover:underline" href={`/experiments/${r.experiment_id}`}>#{r.experiment_id}</Link></>} · imported {fmtDate(r.created_at)} · {r.n_points} points</>}
        actions={<Badge tone={statusTone}>{r.analysis_status.replace("_", " ")}</Badge>} />
      {r.is_demo && <DemoBanner />}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card title="Data" actions={<OriginBadge origin="measured" />}>
            {data.error ? <Alert tone="bad">{data.error}</Alert> : data.data ? <CorrosionPlots run={data.data} fit={fit} demo={r.is_demo} /> : <Spinner label="Loading data" />}
            <p className="mt-2 text-xs text-muted">Plotted from the processed copy in canonical units (V, A/cm², s, Hz, Ω). Fitted lines and shaded regions belong to the current analysis.</p>
          </Card>
          <Card title="Results">
            {!r.current_analysis ? <div className="text-sm text-muted">Not analysed yet. Set parameters and press Analyse.</div> : (
              <div className="flex flex-col gap-3">
                {r.current_analysis.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
                {r.current_analysis.notes.map((n) => <Alert key={n} tone="info">{n}</Alert>)}
                <Table head={["Quantity", "Value", "Unit", "Origin", "Formula", "Status"]}>
                  {r.metrics.map((m) => (
                    <tr key={m.id ?? m.name}>
                      <td className="min-w-56 whitespace-normal! text-ink">{m.label}
                        {(m.assumptions.length > 0 || Object.keys(m.parameters).length > 0) && (
                          <details className="mt-1 text-xs text-muted"><summary className="cursor-pointer">parameters &amp; assumptions</summary>
                            <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{JSON.stringify(m.parameters, null, 1)}</pre>
                            <ul className="list-disc pl-4">{m.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
                          </details>)}
                      </td>
                      <td className="num font-semibold">{fmtNum(m.value)}</td>
                      <td>{unit(m.unit)}</td>
                      <td><OriginBadge origin={m.origin} /></td>
                      <td className="min-w-48 whitespace-normal! font-mono text-[11px] text-ink-2">{m.formula}</td>
                      <td>{m.valid ? <Badge tone="good">valid</Badge> : <Badge tone="bad" title={m.warnings.join(" ")}>unreliable</Badge>}</td>
                    </tr>
                  ))}
                </Table>
              </div>
            )}
          </Card>
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          <Card title="Analysis parameters">
            <div className="flex flex-col gap-3">
              {r.method === "ocp" && <div className="grid grid-cols-2 gap-3">{inp("t_start_s", "Interval start (s)", "Blank = final 20 %")}{inp("t_end_s", "Interval end (s)")}</div>}
              {r.method === "lpr" && (
                <>
                  <div className="grid grid-cols-2 gap-3">{inp("e_corr_V", "E_corr override (V)", "Blank = zero-current crossing")}{inp("half_window_mV", "Half-window (mV)", "Default ±10 mV")}</div>
                  <div className="rounded-md border border-line p-3">
                    <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Stern–Geary coefficient (optional)</div>
                    <div className="grid grid-cols-3 gap-2">{inp("stern_geary_B_V", "B (V)")}{inp("beta_a_V_dec", "β_a (V/dec)")}{inp("beta_c_V_dec", "β_c (V/dec)")}</div>
                    <div className="mt-2">{inp("B_source", "Source of B / Tafel slopes", "Required for i_corr, e.g. 'Tafel fit EC-12' or a literature reference", "text")}</div>
                  </div>
                </>
              )}
              {r.method === "pdp" && (
                <>
                  <div className="grid grid-cols-2 gap-3">
                    {inp("anodic_mV_lo", "Anodic from (mV above E_corr)")}{inp("anodic_mV_hi", "Anodic to (mV)")}
                    {inp("cathodic_mV_lo", "Cathodic from (mV below E_corr)")}{inp("cathodic_mV_hi", "Cathodic to (mV)")}
                  </div>
                  {proposal?.anodic && proposal?.cathodic && (
                    <Button size="sm" onClick={() => setP({ ...p, anodic_mV_lo: String(proposal.anodic![0]), anodic_mV_hi: String(proposal.anodic![1]), cathodic_mV_lo: String(proposal.cathodic![0]), cathodic_mV_hi: String(proposal.cathodic![1]) })}>
                      Use proposed regions ({proposal.anodic.join("–")} / {proposal.cathodic.join("–")} mV)
                    </Button>
                  )}
                  <p className="text-xs text-muted">Leave blank to let the software propose regions; proposals are flagged for review and are excluded from ML datasets until you confirm them here.</p>
                </>
              )}
              {r.method === "eis" && <p className="text-sm text-muted">EIS needs no parameters. Plots and descriptors only; equivalent-circuit fitting is not implemented.</p>}
              {(r.method === "lpr" || r.method === "pdp") && (
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
                      <div className="col-span-2"><LabeledInput label="Source of EW and density" value={mat.source} onChange={(e) => setMat({ ...mat, source: e.target.value })} placeholder="e.g. ASTM G102 Table X, supplier certificate" /></div>
                      <label className="col-span-2 flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" checked={mat.alloy} onChange={(e) => setMat({ ...mat, alloy: e.target.checked })} className="accent-[var(--color-accent)]" />Alloy (EW depends on composition)</label>
                    </div>
                  )}
                  {mat.profile && <p className="mt-2 text-xs text-muted">{materials.data?.find((m) => m.key === mat.profile)?.source}</p>}
                </div>
              )}
              {err && <Alert tone="bad" title="Analysis refused">{err}</Alert>}
              <Button variant="primary" icon={<Play className="size-4" />} busy={busy} onClick={run}>{r.current_analysis ? "Re-analyse" : "Analyse"}</Button>
              {r.current_analysis && <p className="text-xs text-muted">Re-analysis supersedes the current result; earlier analyses remain in the history.</p>}
            </div>
          </Card>
          <Card title="Source and import">
            <KV items={[
              ["Raw file", r.raw_file.original_filename],
              ["SHA-256", <span key="h" className="break-all font-mono text-[11px]">{r.raw_file.sha256}</span>],
              ["Integrity", r.raw_file.integrity === "ok" ? <Badge key="i" tone="good">hash verified</Badge> : <Badge key="i" tone="bad">{r.raw_file.integrity}</Badge>],
              ["Mapping", Object.entries(r.column_mapping).map(([k, v]) => `${k} ← '${v}' [${unit(r.units[k])}]`).join("; ")],
              ["Exposed area", r.exposed_area_cm2 != null ? `${r.exposed_area_cm2} cm² (${r.area_source})` : null],
              ["Reference", r.reference_electrode],
              ["Instrument", r.instrument],
            ]} />
            {r.parser_warnings.length > 0 && <ul className="mt-3 list-disc pl-5 text-xs text-warn">{r.parser_warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
            <div className="mt-3 flex flex-wrap gap-2">
              <a className="inline-flex items-center gap-1 text-sm text-accent hover:underline" href={apiUrl(`/api/artifacts/${r.raw_file.id}/download`)}><Download className="size-4" />Raw file</a>
              <a className="inline-flex items-center gap-1 text-sm text-accent hover:underline" href={apiUrl(`/api/corrosion/runs/${r.id}/processed.csv`)}><Download className="size-4" />Processed CSV</a>
            </div>
          </Card>
          <Card title="History">
            <ol className="space-y-2 text-sm">{r.history.map((h) => <li key={h.id} className="border-l-2 border-line-2 pl-3"><div>{h.summary}</div><div className="text-xs text-muted">{fmtDate(h.created_at)}</div></li>)}</ol>
            {!r.is_demo && (
              <div className="mt-4 border-t border-line pt-3">
                <label htmlFor="del" className="text-xs text-muted">Delete this run (raw and processed files are moved to data/trash). Type <code>EC-{r.id}</code>.</label>
                <div className="mt-1 flex gap-2">
                  <input id="del" className="h-8 w-36 rounded border border-line-2 bg-bg px-2 text-sm" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                  <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} disabled={confirm !== `EC-${r.id}`}
                    onClick={async () => { try { await api(`/api/corrosion/runs/${r.id}?confirm=EC-${r.id}`, { method: "DELETE" }); router.push("/corrosion"); } catch (e) { setErr((e as Error).message); } }}>Delete</Button>
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}
