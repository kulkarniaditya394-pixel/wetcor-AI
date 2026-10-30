"use client";

import { BrainCircuit, FileText, Play } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Plot } from "@/components/Plot";
import { Alert, Badge, Button, Card, DemoBanner, EmptyState, Field, LabeledInput, OriginBadge, PageHeader, Select, Spinner, Table, cx } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, apiUrl } from "@/lib/api";
import { fmtDate, fmtNum, unit } from "@/lib/format";

type Options = { targets: Record<string, { label: string; unit: string; explain: string }>; features: Record<string, { kind: string; label: string }>; wettability_feature: string };
type Readiness = {
  target: string; target_unit: string; n_records: number; n_groups: number; demo_records: number; level: "insufficient" | "exploratory" | "adequate"; can_train: boolean; validated_badge: boolean;
  blocking: string[]; advisories: string[]; n_splits: number; excluded: { run_id: number; specimen_code: string; reason: string }[];
  features: Record<string, { kind: string; missing: number; categories?: Record<string, number>; min?: number | null; max?: number | null; std?: number | null }>;
  target_stats?: { mean: number; std: number | null; min: number; max: number };
};
type RunMetrics = { mae: number; rmse: number; r2: number | null; r2_note: string | null; unit: string; fold_mae_std: number | null; mae_original_units?: number; folds?: { fold: number; test_groups: string[]; mae: number }[] };
type MLRun = { id: number; comparison_id: string; name: string; model_family: string; feature_set: string; features: string[]; target: string; target_unit: string; target_transform: string;
  n_records: number; n_groups: number; split_strategy: string; n_splits: number; seed: number; readiness_level: string; includes_demo: boolean; created_at: string; metrics: RunMetrics;
  oof_predictions?: { specimen_code: string; actual: number; predicted: number }[]; feature_domain?: Record<string, { min?: number; max?: number; categories?: string[] }> };
type Comparison = { comparison_id: string; runs: MLRun[]; comparison: { model_family: string; baseline_mae: number; wettability_mae: number; delta_mae: number; folds_improved: number; n_folds: number; unit: string }[]; interpretation: string };
type History = { comparison_id: string; target: string; created_at: string; n_records: number; n_groups: number; readiness_level: string; includes_demo: boolean; runs: MLRun[] }[];

const LEVEL_TONE = { insufficient: "bad", exploratory: "warn", adequate: "good" } as const;

export default function MLStudio() {
  const opts = useApi<Options>("/api/ml/options");
  const history = useApi<History>("/api/ml/runs");
  const [source, setSource] = useState<"real" | "demo">("real");
  const [target, setTarget] = useState("i_corr");
  const [transform, setTransform] = useState<"log10" | "none">("log10");
  const [feats, setFeats] = useState<string[]>(["material", "surface_preparation", "electrolyte", "temperature_c"]);
  const [seed, setSeed] = useState("42");
  const [ready, setReady] = useState<Readiness | null>(null);
  const [readyErr, setReadyErr] = useState<string | null>(null);
  const [training, setTraining] = useState(false);
  const [trainErr, setTrainErr] = useState<string | null>(null);
  const [cmpId, setCmpId] = useState<string | null>(null);
  const cmp = useApi<Comparison>(cmpId ? `/api/ml/comparisons/${cmpId}` : null);

  useEffect(() => {
    let alive = true;
    setReadyErr(null);
    api<{ readiness: Readiness }>("/api/ml/readiness-check", { method: "POST", json: { target, baseline_features: feats, data_source: source, target_transform: transform } })
      .then((r) => alive && setReady(r.readiness))
      .catch((e: Error) => alive && (setReady(null), setReadyErr(e.message)));
    return () => { alive = false; };
  }, [target, feats, source, transform, history.data]);

  const train = async () => {
    setTraining(true);
    setTrainErr(null);
    try {
      const out = await api<{ comparison_id: string }>("/api/ml/train", { method: "POST", json: { target, baseline_features: feats, data_source: source, target_transform: transform, seed: Number(seed) } });
      setCmpId(out.comparison_id);
      history.reload();
    } catch (e) {
      setTrainErr((e as Error).message);
    } finally {
      setTraining(false);
    }
  };

  const o = opts.data;
  const baseFeatures = o ? Object.entries(o.features).filter(([k]) => k !== o.wettability_feature) : [];
  return (
    <>
      <PageHeader eyebrow="Data · Modelling" title="ML Studio" subtitle="Does water contact angle add predictive information beyond material and test conditions? Baseline and wettability-enhanced models are evaluated on identical specimen-grouped folds." />
      {source === "demo" && <DemoBanner>Models trained here use synthetic records and test the software only.</DemoBanner>}
      <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.9fr)_minmax(0,1.6fr)]">
        <div className="flex flex-col gap-5">
          <Card title="1 · Dataset definition">
            {!o ? <Spinner /> : (
              <div className="flex flex-col gap-3">
                <Field label="Data source">
                  <div role="radiogroup" aria-label="Data source" className="grid grid-cols-2 gap-2">
                    {(["real", "demo"] as const).map((s) => (
                      <button key={s} role="radio" aria-checked={source === s} onClick={() => setSource(s)}
                        className={cx("rounded-md border px-3 py-2 text-sm", source === s ? (s === "demo" ? "border-warn bg-warn-soft text-warn" : "border-accent bg-accent-soft text-accent") : "border-line-2 text-ink-2")}>
                        {s === "real" ? "Laboratory records" : "Demo — synthetic"}
                      </button>
                    ))}
                  </div>
                </Field>
                <Field label="Target" hint={o.targets[target]?.explain}>
                  <Select aria-label="Target" value={target} onChange={(e) => setTarget(e.target.value)}>
                    {Object.entries(o.targets).map(([k, t]) => <option key={k} value={k}>{t.label} [{unit(t.unit)}]</option>)}
                  </Select>
                </Field>
                <Field label="Target transform" hint="Corrosion currents span orders of magnitude; log10 errors are in decades.">
                  <Select aria-label="Target transform" value={transform} onChange={(e) => setTransform(e.target.value as "log10" | "none")}>
                    <option value="log10">log10(target)</option><option value="none">none</option>
                  </Select>
                </Field>
                <fieldset>
                  <legend className="mb-1 text-xs font-medium text-ink-2">Baseline features (contact angle is added only to the enhanced models)</legend>
                  <div className="grid grid-cols-2 gap-1.5">
                    {baseFeatures.map(([k, f]) => (
                      <label key={k} className="flex items-center gap-2 text-sm text-ink-2">
                        <input type="checkbox" className="accent-[var(--color-accent)]" checked={feats.includes(k)} onChange={(e) => setFeats(e.target.checked ? [...feats, k] : feats.filter((x) => x !== k))} />
                        {f.label}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <LabeledInput label="Random seed" type="number" value={seed} onChange={(e) => setSeed(e.target.value)} hint="Recorded with every run; same seed + data gives identical folds." />
              </div>
            )}
          </Card>
          <Card title="2 · Readiness" actions={ready && <Badge tone={LEVEL_TONE[ready.level]}>{ready.level}</Badge>}>
            {readyErr ? <Alert tone="bad">{readyErr}</Alert> : !ready ? <Spinner label="Checking dataset" /> : (
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-3 gap-2 text-center">
                  {[["Records", ready.n_records], ["Specimen groups", ready.n_groups], ["CV folds", ready.n_splits || "—"]].map(([k, v]) => (
                    <div key={k as string} className="rounded-md border border-line bg-panel-2 py-2"><div className="text-[11px] text-muted">{k}</div><div className="num text-lg font-semibold">{v}</div></div>
                  ))}
                </div>
                {ready.validated_badge ? <Alert tone="good" title="Validated-evaluation criteria met">Enough independent groups and no synthetic data under the configured policy.</Alert>
                  : <p className="text-xs text-muted">No validated-evaluation badge: results are {ready.level === "insufficient" ? "not computable" : "exploratory"} under the configured readiness policy (Settings).</p>}
                {ready.blocking.map((b) => <Alert key={b} tone="bad">{b}</Alert>)}
                {ready.advisories.map((a) => <Alert key={a} tone="warn">{a}</Alert>)}
                {ready.excluded.length > 0 && (
                  <details className="text-sm"><summary className="cursor-pointer text-ink-2">{ready.excluded.length} run(s) excluded</summary>
                    <ul className="mt-1 list-disc pl-5 text-xs text-muted">{ready.excluded.map((x) => <li key={x.run_id}>EC-{x.run_id} ({x.specimen_code}): {x.reason}</li>)}</ul></details>
                )}
                <details className="text-sm"><summary className="cursor-pointer text-ink-2">Feature coverage</summary>
                  <Table className="mt-2" head={["Feature", "Missing", "Range / categories"]}>
                    {Object.entries(ready.features).map(([k, f]) => (
                      <tr key={k}><td>{k}</td><td className="num">{f.missing}/{ready.n_records}</td>
                        <td className="whitespace-normal! text-xs text-ink-2">{f.kind === "numeric" ? (f.min != null ? `${fmtNum(f.min)} – ${fmtNum(f.max ?? null)}` : "—") : Object.entries(f.categories ?? {}).map(([c, n]) => `${c} (${n})`).join(", ") || "—"}</td></tr>
                    ))}
                  </Table>
                </details>
                {trainErr && <Alert tone="bad" title="Training refused">{trainErr}</Alert>}
                <Button variant="primary" size="lg" icon={<Play className="size-4" />} disabled={!ready.can_train} busy={training} onClick={train}>
                  {training ? "Training 5 configurations…" : "Train & compare"}
                </Button>
              </div>
            )}
          </Card>
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          {cmpId ? (cmp.loading && !cmp.data ? <Card title="Results"><Spinner /></Card> : cmp.data ? <Results c={cmp.data} /> : <Alert tone="bad">{cmp.error}</Alert>) : (
            <Card title="Results">
              <EmptyState icon={<BrainCircuit className="size-8" />} title="No comparison selected">
                Train a comparison when the readiness check allows it, or open one from the history below. No metrics are shown until an evaluation has actually run.
              </EmptyState>
            </Card>
          )}
          <Card title="Comparison history">
            {!history.data?.length ? <div className="text-sm text-muted">No models trained yet.</div> : (
              <Table head={["Trained", "Target", "Records / groups", "Level", "Data", ""]}>
                {history.data.map((h) => (
                  <tr key={h.comparison_id} className={h.comparison_id === cmpId ? "bg-accent-soft/30" : ""}>
                    <td className="whitespace-nowrap text-xs">{fmtDate(h.created_at)}</td><td>{h.target}</td><td className="num">{h.n_records} / {h.n_groups}</td>
                    <td><Badge tone={LEVEL_TONE[h.readiness_level as keyof typeof LEVEL_TONE] ?? "neutral"}>{h.readiness_level}</Badge></td>
                    <td>{h.includes_demo ? <Badge tone="warn">demo</Badge> : <Badge tone="good">real</Badge>}</td>
                    <td><Button size="sm" variant="ghost" onClick={() => setCmpId(h.comparison_id)}>Open</Button></td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function Results({ c }: { c: Comparison }) {
  const r0 = c.runs[0];
  const u = r0.metrics.unit;
  const scatter = useMemo(() => {
    const traces = c.runs.filter((r) => r.model_family !== "mean").map((r) => ({
      x: r.oof_predictions?.map((p) => p.actual), y: r.oof_predictions?.map((p) => p.predicted), text: r.oof_predictions?.map((p) => p.specimen_code),
      mode: "markers", type: "scatter", name: r.name, marker: { size: 7, opacity: 0.8 },
    }));
    const all = c.runs.flatMap((r) => r.oof_predictions?.flatMap((p) => [p.actual, p.predicted]) ?? []);
    const lo = Math.min(...all), hi = Math.max(...all);
    traces.push({ x: [lo, hi], y: [lo, hi], text: undefined, mode: "lines", type: "scatter", name: "ideal", marker: { size: 0, opacity: 1 }, line: { dash: "dot", color: "#8195b0" } } as never);
    return traces;
  }, [c]);
  return (
    <>
      <Card title="Model comparison (out-of-fold)" actions={<a href={apiUrl(`/api/reports/ml/${r0.id}`)} target="_blank" rel="noreferrer"><Button size="sm" icon={<FileText className="size-3.5" />}>Report</Button></a>}>
        <div className="mb-3 flex flex-wrap gap-1.5 text-xs">
          <Badge className="normal-case tracking-normal">{r0.target} [{unit(r0.target_unit)}]</Badge><Badge>transform {r0.target_transform}</Badge><Badge>{r0.split_strategy}</Badge>
          <Badge>{r0.n_records} records · {r0.n_groups} groups · {r0.n_splits} folds</Badge>
          <Badge tone={LEVEL_TONE[r0.readiness_level as keyof typeof LEVEL_TONE] ?? "neutral"}>{r0.readiness_level}</Badge>{r0.includes_demo && <Badge tone="warn">Demo — synthetic</Badge>}
        </div>
        <Table head={["Model configuration", <>MAE <span className="normal-case">[{unit(u)}]</span></>, <>RMSE <span className="normal-case">[{unit(u)}]</span></>, "R²", "Fold MAE SD", "Groups", "Status"]}>
          {c.runs.map((r) => (
            <tr key={r.id} className={r.feature_set === "wettability" ? "bg-accent-soft/20" : ""}>
              <td>{r.name}</td><td className="num">{fmtNum(r.metrics.mae)}</td><td className="num">{fmtNum(r.metrics.rmse)}</td>
              <td className="num" title={r.metrics.r2_note ?? undefined}>{r.metrics.r2 == null ? "N/A" : fmtNum(r.metrics.r2, 3)}</td>
              <td className="num">{fmtNum(r.metrics.fold_mae_std)}</td><td className="num">{r.n_groups}</td><td><Badge tone="good">recorded</Badge></td>
            </tr>
          ))}
        </Table>
        <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wider text-muted">Baseline vs + contact angle</h3>
        <Table head={["Family", "Baseline MAE", "+ CA MAE", "Δ MAE", "Folds improved"]}>
          {c.comparison.map((x) => (
            <tr key={x.model_family}><td>{x.model_family.replace("_", " ")}</td><td className="num">{fmtNum(x.baseline_mae)}</td><td className="num">{fmtNum(x.wettability_mae)}</td>
              <td className={cx("num font-semibold", x.delta_mae < 0 ? "text-good" : x.delta_mae > 0 ? "text-bad" : "")}>{x.delta_mae > 0 ? "+" : ""}{fmtNum(x.delta_mae)}</td>
              <td className="num">{x.folds_improved}/{x.n_folds}</td></tr>
          ))}
        </Table>
        <div className="mt-3"><Alert tone={r0.readiness_level === "adequate" && !r0.includes_demo ? "info" : "warn"} title="Reading">{c.interpretation}</Alert></div>
      </Card>
      <Card title="Actual vs predicted (held-out specimens)" actions={<OriginBadge origin="predicted" />}>
        <Plot data={scatter} layout={{ xaxis: { title: { text: `Actual [${unit(u)}]` } }, yaxis: { title: { text: `Predicted [${unit(u)}]` } } }} height={360} label="Out-of-fold actual versus predicted values" filename="wetcor_actual_vs_predicted" />
      </Card>
      <PredictPanel runs={c.runs.filter((r) => r.model_family !== "mean")} />
    </>
  );
}

type Prediction = { label: string; prediction: number; target_unit: string; target: string; warnings: string[]; uncertainty: string; model: { name: string; dataset_hash: string; trained_at: string };
  validation: { mae: number; rmse: number; r2: number | null; unit: string; n_groups: number; split_strategy: string; readiness_level: string }; inputs: Record<string, unknown> };

function PredictPanel({ runs }: { runs: MLRun[] }) {
  const [runId, setRunId] = useState(runs.find((r) => r.feature_set === "wettability")?.id ?? runs[0]?.id);
  const run = runs.find((r) => r.id === runId);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [out, setOut] = useState<Prediction | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!run) return null;
  return (
    <Card title="Prediction (saved model)" actions={<OriginBadge origin="predicted" />}>
      <div className="flex flex-col gap-3">
        <Field label="Model"><Select aria-label="Model for prediction" value={runId} onChange={(e) => { setRunId(Number(e.target.value)); setOut(null); }}>
          {runs.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
        </Select></Field>
        <div className="grid gap-3 sm:grid-cols-2">
          {run.features.map((f) => {
            const d = run.feature_domain?.[f];
            return d?.categories ? (
              <Field key={f} label={f} hint="Categories seen in training (others are treated as unknown).">
                <Select aria-label={f} value={inputs[f] ?? ""} onChange={(e) => setInputs({ ...inputs, [f]: e.target.value })}>
                  <option value="">(missing)</option>{d.categories.map((c) => <option key={c}>{c}</option>)}
                </Select>
              </Field>
            ) : (
              <LabeledInput key={f} label={f} type="number" step="any" value={inputs[f] ?? ""} onChange={(e) => setInputs({ ...inputs, [f]: e.target.value })}
                hint={d?.min != null ? `training range ${fmtNum(d.min)} – ${fmtNum(d.max ?? null)}` : undefined} />
            );
          })}
        </div>
        <Button variant="primary" busy={busy} onClick={async () => {
          setBusy(true); setErr(null);
          try { setOut(await api<Prediction>("/api/ml/predict", { method: "POST", json: { run_id: run.id, inputs } })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
        }}>Predict</Button>
        {err && <Alert tone="bad">{err}</Alert>}
        {out && (
          <div className="rounded-md border border-pred/40 bg-[#1a1530] p-3">
            <div className="flex items-center gap-2 text-xs text-pred">{out.label}</div>
            <div className="num mt-1 text-2xl font-semibold">{fmtNum(out.prediction, 3)} <span className="text-base text-ink-2">{unit(out.target_unit)}</span></div>
            <div className="mt-1 text-xs text-muted">{out.model.name} · trained {fmtDate(out.model.trained_at)} · dataset {out.model.dataset_hash.slice(0, 12)}… · out-of-fold MAE {fmtNum(out.validation.mae)} {out.validation.unit} on {out.validation.n_groups} groups ({out.validation.readiness_level})</div>
            <div className="mt-2 text-xs text-muted">{out.uncertainty}</div>
            {out.warnings.map((w) => <div key={w} className="mt-2"><Alert tone="warn">{w}</Alert></div>)}
          </div>
        )}
        <p className="text-xs text-muted">Predictions are model outputs, never measurements, and are not stored as experimental data.</p>
      </div>
    </Card>
  );
}
