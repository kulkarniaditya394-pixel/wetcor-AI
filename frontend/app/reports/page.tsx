"use client";

import { Download, FileText } from "lucide-react";
import { useState } from "react";
import { Alert, Button, Card, Field, PageHeader, Select } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { apiUrl, type Experiment, type Page } from "@/lib/api";
import { fmtDate } from "@/lib/format";

const EXPORTS = [
  ["specimens", "Specimen metadata", "All specimen records."],
  ["experiments", "Experiments", "Test conditions per experiment."],
  ["contact_angles", "Contact-angle observations", "Measured angles, methods, image hashes."],
  ["corrosion_runs", "Electrochemical runs", "Source files, hashes, mapping, areas."],
  ["metrics", "Derived corrosion parameters", "Calculated values with formulas and validity."],
  ["dataset", "Combined ML dataset", "One row per run with a valid i_corr target."],
  ["ml_runs", "ML comparison results", "Every recorded model configuration and its metrics."],
  ["ml_predictions", "Actual vs predicted", "Out-of-fold predictions for every model."],
] as const;

export default function Reports() {
  const [demo, setDemo] = useState(false);
  const exps = useApi<Page<Experiment>>(`/api/experiments?page_size=500${demo ? "&include_demo=true" : ""}`);
  const ml = useApi<{ comparison_id: string; target: string; created_at: string; includes_demo: boolean; runs: { id: number }[] }[]>("/api/ml/runs");
  const [exp, setExp] = useState("");
  const [cmp, setCmp] = useState("");
  const q = demo ? "?include_demo=true" : "";
  return (
    <>
      <PageHeader eyebrow="Data · Output" title="Reports & Exports" subtitle="Everything exported here is read from the local database. Reports open as print-ready pages (use the browser's Print → Save as PDF)." />
      <label className="mb-4 flex items-center gap-2 text-sm text-ink-2">
        <input type="checkbox" className="accent-[var(--color-warn)]" checked={demo} onChange={(e) => setDemo(e.target.checked)} />
        Include DEMO — synthetic records (rows are flagged; the combined dataset switches to demo-only)
      </label>
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Experiment report">
          <div className="flex flex-col gap-3">
            <Field label="Experiment">
              <Select aria-label="Experiment for report" value={exp} onChange={(e) => setExp(e.target.value)}>
                <option value="">Select…</option>
                {(exps.data?.items ?? []).map((e) => <option key={e.id} value={e.id}>{e.code} · {e.specimen_code}{e.is_demo ? " · DEMO" : ""}</option>)}
              </Select>
            </Field>
            <p className="text-xs text-muted">Specimen and experiment IDs, measured values with units, calculation methods and assumptions, warnings, source-file SHA-256 hashes and plots.</p>
            <div className="flex gap-2">
              <a href={exp ? apiUrl(`/api/reports/experiment/${exp}`) : undefined} target="_blank" rel="noreferrer" aria-disabled={!exp}><Button variant="primary" disabled={!exp} icon={<FileText className="size-4" />}>Open report</Button></a>
              <a href={exp ? apiUrl(`/api/reports/experiment/${exp}?format=json`) : undefined} target="_blank" rel="noreferrer" aria-disabled={!exp}><Button disabled={!exp}>JSON</Button></a>
            </div>
          </div>
        </Card>
        <Card title="ML comparison report">
          <div className="flex flex-col gap-3">
            <Field label="Comparison">
              <Select aria-label="ML comparison for report" value={cmp} onChange={(e) => setCmp(e.target.value)}>
                <option value="">Select…</option>
                {(ml.data ?? []).map((c) => <option key={c.comparison_id} value={c.runs[0]?.id}>{c.target} · {fmtDate(c.created_at)}{c.includes_demo ? " · DEMO" : ""}</option>)}
              </Select>
            </Field>
            {ml.data?.length === 0 && <Alert tone="info">No ML comparisons have been trained yet.</Alert>}
            <a href={cmp ? apiUrl(`/api/reports/ml/${cmp}`) : undefined} target="_blank" rel="noreferrer" aria-disabled={!cmp}><Button variant="primary" disabled={!cmp} icon={<FileText className="size-4" />}>Open report</Button></a>
          </div>
        </Card>
        <Card title="CSV exports" className="lg:col-span-2">
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {EXPORTS.map(([kind, label, help]) => (
              <li key={kind} className="flex flex-col gap-2 rounded-md border border-line p-3">
                <div className="text-sm font-semibold">{label}</div>
                <div className="flex-1 text-xs text-muted">{help}</div>
                <a href={apiUrl(`/api/exports/${kind}.csv${q}`)} download><Button size="sm" icon={<Download className="size-3.5" />}>{kind}.csv</Button></a>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">Original instrument files and images are downloadable from each record page (by record ID; the stored file and its SHA-256 are verified on every download).</p>
        </Card>
      </div>
    </>
  );
}
