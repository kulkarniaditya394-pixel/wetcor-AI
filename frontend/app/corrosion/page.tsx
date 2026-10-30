"use client";

import { FileUp, Upload } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useRef, useState, type DragEvent } from "react";
import { Plot } from "@/components/Plot";
import { EngineBanner } from "@/components/EngineBanner";
import { QuickAnalysis } from "@/components/QuickAnalysis";
import { SpecimenPicker } from "@/components/SpecimenPicker";
import { Alert, Badge, Button, Card, EmptyState, Field, LabeledInput, PageHeader, Select, Table, Textarea, cx } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, form, type CorrosionRun, type Specimen } from "@/lib/api";
import { fmtDate, unit } from "@/lib/format";
import { isStaticDemo } from "@/lib/mode";

type Method = "ocp" | "lpr" | "pdp" | "eis";
type Preview = {
  filename: string; size_bytes: number; encoding: string; delimiter: string; decimal_comma: boolean; columns: string[]; units_row: string[] | null; n_rows: number;
  metadata: Record<string, string>; warnings: string[]; preview_rows: (number | null)[][]; raw_head: string[];
  suggestion: { mapping: Record<string, string>; units: Record<string, string | null>; imag_convention: "as_is" | "negated"; suggested_method: Method | null };
  columns_data: Record<string, (number | null)[]>;
};
type Methods = { methods: Record<Method, string>; required: Record<Method, string[][]>; allowed_roles: Record<Method, string[]>; units: Record<string, Record<string, number>> };

const ROLE_Q: Record<string, string> = { time: "time", potential: "potential", current: "current", current_density: "current_density", frequency: "frequency", z_real: "impedance", z_imag: "impedance", z_mod: "impedance", phase: "phase" };
const ROLE_LABEL: Record<string, string> = { time: "Time", potential: "Potential", current: "Current (total)", current_density: "Current density", frequency: "Frequency", z_real: "Real impedance Z'", z_imag: "Imaginary impedance", z_mod: "|Z| (optional check)", phase: "Phase (optional check)" };
const METHOD_HELP: Record<Method, string> = {
  ocp: "Potential vs time at open circuit. Gives OCP statistics and drift only — never a corrosion rate.",
  lpr: "Small sweep (typically ±10–25 mV) around E_corr. Gives R_p; i_corr only with a documented Stern–Geary B.",
  pdp: "Wide polarisation sweep. Tafel extrapolation on reviewed linear regions gives i_corr, β_a, β_c.",
  eis: "Impedance spectrum. Nyquist and Bode plots and simple descriptors; no automatic corrosion rate.",
};

export default function CorrosionPage() {
  const router = useRouter();
  const meta = useApi<Methods>("/api/corrosion/methods");
  const hosted = isStaticDemo();
  const runs = useApi<CorrosionRun[]>(hosted ? null : "/api/corrosion/runs?limit=20");
  const [quickKey, setQuickKey] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pv, setPv] = useState<Preview | null>(null);
  const [pvErr, setPvErr] = useState<string | null>(null);
  const [method, setMethod] = useState<Method | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [units, setUnits] = useState<Record<string, string | null>>({});
  const [imag, setImag] = useState<"as_is" | "negated">("as_is");
  const [anodicNeg, setAnodicNeg] = useState(false);
  const [spec, setSpec] = useState<{ id: number | null; exp: number | null; s?: Specimen }>({ id: null, exp: null });
  const [area, setArea] = useState("");
  const [ref, setRef] = useState("");
  const [instrument, setInstrument] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [importErr, setImportErr] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);

  const load = async (f: File) => {
    setFile(f); setPv(null); setPvErr(null); setImportErr(null); setBusy(true);
    try {
      const p = await api<Preview>("/api/corrosion/import/preview", { method: "POST", body: form({ file: [f, f.name] }) });
      setPv(p);
      setMethod(p.suggestion.suggested_method);
      setMapping(p.suggestion.mapping);
      setUnits(p.suggestion.units);
      setImag(p.suggestion.imag_convention);
      const refKey = Object.keys(p.metadata).find((k) => /ref/i.test(k));
      if (refKey) setRef(p.metadata[refKey]);
    } catch (e) {
      setPvErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const roles = method && meta.data ? meta.data.allowed_roles[method] : [];
  const issues = useMemo(() => {
    if (!pv || !method || !meta.data) return ["Choose a measurement method."];
    const out: string[] = [];
    for (const group of meta.data.required[method]) if (!group.some((r) => mapping[r])) out.push(`Map a column for ${group.map((r) => ROLE_LABEL[r].toLowerCase()).join(" or ")}.`);
    for (const r of roles) if (mapping[r] && !units[r]) out.push(`Select the unit for ${ROLE_LABEL[r].toLowerCase()} ('${mapping[r]}').`);
    if ((method === "lpr" || method === "pdp") && mapping.current && !mapping.current_density && !area && !spec.s?.exposed_area_cm2)
      out.push("Enter the exposed electrode area (or record it on the specimen) to convert current to current density.");
    if (!hosted && !spec.id) out.push("Select the specimen this run belongs to.");
    return out;
  }, [pv, method, meta.data, mapping, units, roles, area, spec]);

  const state = !file ? ["Awaiting file", "neutral"] : pvErr ? ["Error: file not readable", "bad"] : !pv ? ["Reading file…", "neutral"] : issues.length ? ["Columns require mapping", "warn"] : [hosted ? "Ready to analyse" : "Ready to import", "good"];

  const previewPlot = useMemo(() => {
    if (!pv || !method || !meta.data || issues.some((i) => i.startsWith("Map") || i.startsWith("Select the unit"))) return null;
    const f = (role: string) => {
      const c = pv.columns_data[mapping[role]] ?? [];
      const k = meta.data!.units[ROLE_Q[role]]?.[units[role] ?? ""] ?? NaN;
      return c.map((v) => (v == null ? null : v * k));
    };
    if (method === "ocp") return { data: [{ x: f("time"), y: f("potential"), mode: "lines", name: "E" }], layout: { xaxis: { title: { text: "Time (s)" } }, yaxis: { title: { text: "E (V)" } } } };
    if (method === "eis") {
      const zi = f("z_imag").map((v) => (v == null ? null : imag === "negated" ? v : -v));
      return { data: [{ x: f("z_real"), y: zi, mode: "lines+markers", name: "−Z''" }], layout: { xaxis: { title: { text: "Z' (Ω)" } }, yaxis: { title: { text: "−Z'' (Ω)" } } } };
    }
    const cur = mapping.current_density ? f("current_density") : f("current");
    const sign = anodicNeg ? -1 : 1;
    return method === "pdp"
      ? { data: [{ x: cur.map((v) => (v ? Math.abs(v) : null)), y: f("potential"), mode: "lines", name: "|i|" }], layout: { xaxis: { title: { text: mapping.current_density ? "|i| (A/cm²)" : "|I| (A)" }, type: "log" }, yaxis: { title: { text: "E (V)" } } } }
      : { data: [{ x: cur.map((v) => (v == null ? null : v * sign)), y: f("potential"), mode: "markers", marker: { size: 3 }, name: "I" }], layout: { xaxis: { title: { text: mapping.current_density ? "i (A/cm²)" : "I (A)" } }, yaxis: { title: { text: "E (V)" } } } };
  }, [pv, method, meta.data, mapping, units, imag, anodicNeg, issues]);

  const submit = async () => {
    if (!file || !method || issues.length) return;
    setBusy(true);
    setImportErr(null);
    try {
      const m = { method, mapping: Object.fromEntries(Object.entries(mapping).filter(([r, c]) => c && roles.includes(r))),
        units: Object.fromEntries(Object.entries(units).filter(([r]) => mapping[r] && roles.includes(r))), imag_convention: imag, anodic_negative: anodicNeg,
        specimen_id: spec.id, experiment_id: spec.exp, exposed_area_cm2: area ? Number(area) : null, area_source: area ? "entered at import" : null,
        reference_electrode: ref || null, instrument: instrument || null, notes: notes || null };
      const run = await api<CorrosionRun>("/api/corrosion/import", { method: "POST", body: form({ file: [file, file.name], meta: JSON.stringify(m) }) });
      router.push(`/corrosion/runs/${run.id}`);
    } catch (e) {
      setImportErr((e as Error).message);
      setBusy(false);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f) load(f);
  };

  return (
    <>
      <PageHeader eyebrow="Instrument · Potentiostat import" title="Corrosion Lab" subtitle={hosted ? "Drop a potentiostat export (CSV, TSV, TXT), map columns and units, and get the corrosion parameters calculated in your browser — OCP, LPR, polarisation (Tafel) or EIS." : "Import potentiostat exports (CSV, TSV, TXT), map columns and units explicitly, then analyse OCP, LPR, polarisation or EIS data."}
        actions={<Badge tone={state[1] as "neutral"}>{state[0]}</Badge>} />
      <EngineBanner />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card title="1 · Measurement file">
            <div
              onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)} onDrop={onDrop}
              className={cx("flex flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors", drag ? "border-accent bg-accent-soft/30" : "border-line-2")}
            >
              <FileUp className="size-8 text-muted" aria-hidden />
              <div className="text-sm text-ink-2">{file ? <><strong>{file.name}</strong> · {(file.size / 1024).toFixed(1)} kB</> : "Drag a potentiostat export here"}</div>
              <input ref={fileRef} type="file" accept=".csv,.tsv,.txt,.dta,.dat" className="hidden" aria-label="Choose measurement file"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) load(f); e.target.value = ""; }} />
              <Button icon={<Upload className="size-4" />} busy={busy && !pv} onClick={() => fileRef.current?.click()}>{file ? "Choose another file" : "Browse…"}</Button>
              <p className="text-xs text-muted">The file is parsed locally by the WETCOR backend. The original bytes are stored unmodified only when you import.</p>
            </div>
            {pvErr && <div className="mt-3"><Alert tone="bad" title="File could not be parsed">{pvErr}</Alert></div>}
          </Card>

          {pv && (
            <Card title="2 · Preview">
              <div className="mb-3 flex flex-wrap gap-1.5">
                <Badge>{pv.encoding}</Badge><Badge>{pv.delimiter} delimited</Badge>{pv.decimal_comma && <Badge tone="warn">decimal comma</Badge>}<Badge>{pv.n_rows} data rows</Badge><Badge>{pv.columns.length} columns</Badge>
              </div>
              {pv.warnings.map((w) => <div key={w} className="mb-2"><Alert tone="warn">{w}</Alert></div>)}
              <details className="mb-3">
                <summary className="cursor-pointer text-sm text-ink-2">Original first lines</summary>
                <pre className="scroll-thin mt-2 max-h-56 overflow-auto rounded border border-line bg-bg p-2 font-mono text-[11px] text-ink-2">{pv.raw_head.join("\n")}</pre>
              </details>
              <Table head={pv.columns.map((c, i) => <span key={i}>{c}{pv.units_row?.[i] ? <span className="ml-1 normal-case text-ink-2">[{pv.units_row[i]}]</span> : null}</span>)}>
                {pv.preview_rows.slice(0, 8).map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j} className="num font-mono text-xs">{v ?? "—"}</td>)}</tr>)}
              </Table>
              {Object.keys(pv.metadata).length > 0 && (
                <details className="mt-3"><summary className="cursor-pointer text-sm text-ink-2">Header metadata ({Object.keys(pv.metadata).length})</summary>
                  <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs">{Object.entries(pv.metadata).slice(0, 40).map(([k, v]) => <div key={k} className="contents"><dt className="text-muted">{k}</dt><dd className="break-all">{v}</dd></div>)}</dl>
                </details>
              )}
            </Card>
          )}

          {pv && meta.data && (
            <Card title="3 · Method, columns and units">
              <fieldset className="mb-4">
                <legend className="mb-2 text-xs font-medium text-ink-2">Test method <span className="text-accent">*</span></legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(Object.keys(meta.data.methods) as Method[]).map((m) => (
                    <label key={m} className={cx("cursor-pointer rounded-md border px-3 py-2 text-sm", method === m ? "border-accent bg-accent-soft/40" : "border-line-2 hover:border-accent/50")}>
                      <input type="radio" name="method" value={m} checked={method === m} onChange={() => setMethod(m)} className="mr-2 accent-[var(--color-accent)]" />
                      <strong>{m.toUpperCase()}</strong> — {meta.data!.methods[m]}
                      <div className="mt-1 text-xs text-muted">{METHOD_HELP[m]}</div>
                    </label>
                  ))}
                </div>
                {pv.suggestion.suggested_method && <p className="mt-2 text-xs text-muted">Suggested from the file: {pv.suggestion.suggested_method.toUpperCase()} (verify).</p>}
              </fieldset>
              {method && (
                <div className="flex flex-col gap-2">
                  {roles.map((role) => {
                    const req = meta.data!.required[method].some((g) => g.includes(role));
                    const opts = Object.keys(meta.data!.units[ROLE_Q[role]] ?? {});
                    return (
                      <div key={role} className="grid items-end gap-2 sm:grid-cols-[180px_1fr_150px]">
                        <div className="text-sm text-ink-2">{ROLE_LABEL[role]}{req && <span className="text-accent"> *</span>}</div>
                        <Select aria-label={`Column for ${ROLE_LABEL[role]}`} value={mapping[role] ?? ""} onChange={(e) => setMapping({ ...mapping, [role]: e.target.value })}>
                          <option value="">— not mapped —</option>
                          {pv.columns.map((c) => <option key={c}>{c}</option>)}
                        </Select>
                        <Select aria-label={`Unit for ${ROLE_LABEL[role]}`} value={units[role] ?? ""} disabled={!mapping[role]} onChange={(e) => setUnits({ ...units, [role]: e.target.value || null })}
                          className={mapping[role] && !units[role] ? "border-warn" : ""}>
                          <option value="">unit…</option>
                          {opts.map((u) => <option key={u} value={u}>{unit(u)}</option>)}
                        </Select>
                      </div>
                    );
                  })}
                  {method === "eis" && mapping.z_imag && (
                    <Field label="Imaginary column contains"><Select aria-label="Imaginary sign convention" value={imag} onChange={(e) => setImag(e.target.value as "as_is" | "negated")}>
                      <option value="as_is">Z'' (negative for capacitive response)</option><option value="negated">−Z'' (positive for capacitive response)</option>
                    </Select></Field>
                  )}
                  {(method === "lpr" || method === "pdp") && (
                    <label className="mt-1 flex items-center gap-2 text-sm text-ink-2">
                      <input type="checkbox" checked={anodicNeg} onChange={(e) => setAnodicNeg(e.target.checked)} className="accent-[var(--color-accent)]" />
                      File uses anodic-negative current convention (invert so anodic is positive)
                    </label>
                  )}
                  <p className="text-xs text-muted">Units shown beside every variable are applied exactly as selected; nothing is inferred silently.</p>
                </div>
              )}
            </Card>
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          {pv && (
            <Card title={hosted ? "4 · Test metadata" : "4 · Specimen and test metadata"}>
              <div className="flex flex-col gap-3">
                {!hosted && <SpecimenPicker specimenId={spec.id} experimentId={spec.exp} onChange={(id, exp, s) => setSpec({ id, exp, s })} />}
                <LabeledInput label="Exposed electrode area (cm²)" type="number" min={0} step="any" value={area} onChange={(e) => setArea(e.target.value)}
                  hint={spec.s?.exposed_area_cm2 ? `Leave blank to use the specimen record (${spec.s.exposed_area_cm2} cm²).` : "Required when the file has total current only."} />
                <LabeledInput label="Reference electrode" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="e.g. SCE, Ag/AgCl (3 M KCl)" />
                <LabeledInput label="Instrument" value={instrument} onChange={(e) => setInstrument(e.target.value)} placeholder="Potentiostat model / software" />
                <Field label="Notes"><Textarea aria-label="Run notes" value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
              </div>
            </Card>
          )}
          {pv && (
            <Card title={hosted ? "5 · Validate and analyse" : "5 · Validate and import"}>
              {issues.length ? <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-warn">{issues.map((i) => <li key={i}>{i}</li>)}</ul> : <Alert tone="good">Mapping complete. Review the plot, then {hosted ? "analyse" : "import"}.</Alert>}
              {previewPlot && <Plot data={previewPlot.data} layout={{ ...previewPlot.layout, margin: { l: 60, r: 10, t: 10, b: 45 }, showlegend: false }} height={240} label="Preview plot of mapped data" />}
              {importErr && <div className="mt-3"><Alert tone="bad" title="Import refused">{importErr}</Alert></div>}
              {hosted ? (
                <Button className="mt-3 w-full" variant="primary" size="lg" disabled={!!issues.length} onClick={() => { setQuickKey((k) => k + 1); setTimeout(() => document.getElementById("quick-analysis")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); }}>Analyse (not saved)</Button>
              ) : (
                <Button className="mt-3 w-full" variant="primary" size="lg" disabled={!!issues.length} busy={busy} onClick={submit}>Import run</Button>
              )}
            </Card>
          )}
          {!pv && (
            <Card title="Supported methods">
              <dl className="flex flex-col gap-3 text-sm">
                {(Object.keys(METHOD_HELP) as Method[]).map((m) => (
                  <div key={m} className="grid grid-cols-[48px_1fr] gap-3">
                    <dt className="pt-0.5 font-mono text-xs font-semibold text-accent">{m.toUpperCase()}</dt>
                    <dd className="text-ink-2">{METHOD_HELP[m]}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-4 border-t border-line pt-3 text-xs text-muted">
                Comma, tab, semicolon (incl. decimal comma) and whitespace exports are recognised, including Gamry-style unit rows. Synthetic sample files to try: <code>data/demo/DEMO_SYNTHETIC_*</code>.
              </p>
            </Card>
          )}
          {!hosted && <Card title="Recent runs">
            {runs.error ? <Alert tone="bad">{runs.error}</Alert> : !runs.data?.length ? (
              <EmptyState title="No electrochemical runs yet">Import an export from your potentiostat. Demo files are in <code>data/demo/</code>.</EmptyState>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {runs.data.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2 py-2">
                    <Link className="text-accent hover:underline" href={`/corrosion/runs/${r.id}`}>EC-{r.id} · {r.method.toUpperCase()}</Link>
                    <span className="text-xs text-muted">{fmtDate(r.created_at)}</span>
                    <Badge tone={r.analysis_status === "analysed" ? "good" : r.analysis_status === "imported" ? "neutral" : "warn"}>{r.analysis_status.replace("_", " ")}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>}
        </div>
      </div>
      {hosted && quickKey > 0 && file && method && (
        <QuickAnalysis key={quickKey} input={{ file, method, mapping, units, imag, anodicNeg, area, reference: ref }} />
      )}
    </>
  );
}
