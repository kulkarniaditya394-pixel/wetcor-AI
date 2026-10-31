"use client";

import { ClipboardPaste, Download, Printer, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useApi } from "@/hooks/useApi";
import { api, type Metric } from "@/lib/api";
import { fmtNum, unit } from "@/lib/format";
import { Alert, Badge, Button, Card, Field, LabeledInput, OriginBadge, Select, StatusDot, Table, Textarea, cx } from "./ui";

type Parsed = { n_cycles: number; readings: Record<string, number>; spread: Record<string, number>; device_result: string | null; device_verdict: string;
  unrecognised_lines: string[]; missing: string[]; warnings: string[] };
type Check = { key: string; label: string; value: string; status: string; note: string };
type Result = {
  device_result: string | null; device_verdict: string; n_cycles: number; comparison: string; comparison_text: string; agrees_with_device: boolean | null;
  currents: { good_a: number; corroded_a: number; delta_a: number; delta_percent: number | null; calibrated: boolean };
  resolution: { adc_step_a: number | null; floor_a: number | null; resolved: boolean | null }; sensor: { variant: string } | null;
  checks: Check[]; metrics: Metric[]; needs: string[]; warnings: string[]; notes: string[]; severity: { value_mm_y: number; label: string; basis: string } | null;
};
type MaterialProfile = { key: string; label: string; equivalent_weight_g_eq: number; density_g_cm3: number; source: string };

const FIELDS: [string, string, string][] = [
  ["good_acs_v", "Good ACS712 AO", "V"], ["corroded_acs_v", "Corroded ACS712 AO", "V"], ["good_current_a", "Good current", "A"], ["corroded_current_a", "Corroded current", "A"],
  ["current_diff_a", "Current difference", "A"], ["good_lm_v", "Good LM393 AO", "V"], ["corroded_lm_v", "Corroded LM393 AO", "V"], ["lm_diff_abs_v", "Absolute LM difference", "V"],
];
const EXAMPLE = `Good ACS712 AO: 2.527 V
Corroded ACS712 AO: 2.528 V
Good current: 0.145 A
Corroded current: 0.153 A
Current difference: 0.009 A
Good LM393 AO: 5.000 V
Corroded LM393 AO: 4.959 V
Signed LM difference: -0.041 V
Absolute LM difference: 0.041 V
RESULT: HEALTHY ELECTRODE`;
const STORE = "wetcor.rig.setup";
const KEY_RATES = ["rig_gravimetric_rate", "rig_faraday_rate", "rig_mass_loss_rate", "rig_current_density"];

function loadSetup() {
  try {
    return JSON.parse(localStorage.getItem(STORE) ?? "{}") as Record<string, string>;
  } catch {
    return {};
  }
}

/** Arduino rig: paste the Serial Monitor output or type the values; everything else is calculated. */
export function RigPanel() {
  const materials = useApi<MaterialProfile[]>("/api/materials");
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<Parsed | null>(null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [verdictText, setVerdictText] = useState("");
  const [setup, setSetup] = useState<Record<string, string>>({});
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const edited = useRef(false);

  useEffect(() => setSetup(loadSetup()), []);
  const set = (k: string, v: string) => {
    const next = { ...setup, [k]: v };
    setSetup(next);
    try {
      localStorage.setItem(STORE, JSON.stringify({ area: next.area, profile: next.profile, ew: next.ew, rho: next.rho, source: next.source }));
    } catch {
      /* private window: the form still works */
    }
  };

  // Paste -> read the text
  useEffect(() => {
    if (!text.trim()) return;
    const id = setTimeout(async () => {
      try {
        const p = await api<Parsed>("/api/corrosion/rig/parse", { method: "POST", json: { text } });
        setParsed(p);
        edited.current = false;
        setVals(Object.fromEntries(Object.entries(p.readings).map(([k, v]) => [k, String(+v.toFixed(5))])));
        setVerdictText(p.device_result ?? "");
        setErr(null);
      } catch (e) {
        setErr((e as Error).message);
      }
    }, 250);
    return () => clearTimeout(id);
  }, [text]);

  // Values or setup -> calculate
  useEffect(() => {
    if (!vals.good_current_a || !vals.corroded_current_a) {
      setRes(null);
      return;
    }
    const n = (s?: string) => (s === undefined || s.trim() === "" || Number.isNaN(Number(s)) ? undefined : Number(s));
    const id = setTimeout(async () => {
      try {
        const readings = Object.fromEntries(Object.entries(vals).map(([k, v]) => [k, n(v)]).filter(([, v]) => v !== undefined));
        const settings = { exposed_area_cm2: n(setup.area), zero_good_ao_v: n(setup.zero_good), zero_corroded_ao_v: n(setup.zero_corroded), mass_before_g: n(setup.m0), mass_after_g: n(setup.m1),
          exposure_h: n(setup.hours), sensitivity_v_per_a: n(setup.sens) };
        const material = setup.profile ? { profile: setup.profile } : (setup.ew || setup.rho) ? { equivalent_weight_g_eq: n(setup.ew) ?? null, density_g_cm3: n(setup.rho) ?? null, source: setup.source || null } : null;
        setRes(await api<Result>("/api/corrosion/rig/analyze", { method: "POST", json: { readings, settings, material, device_result: verdictText || null,
          spread: edited.current ? {} : parsed?.spread ?? {}, n_cycles: edited.current ? 1 : parsed?.n_cycles ?? 1 } }));
        setErr(null);
      } catch (e) {
        setErr((e as Error).message);
      }
    }, 200);
    return () => clearTimeout(id);
  }, [vals, setup, verdictText, parsed]);

  const csv = () => {
    if (!res) return;
    const rows = [["quantity", "value", "unit", "origin"],
      ...FIELDS.filter(([k]) => vals[k]).map(([k, l, u]) => [l, vals[k], u, "measured (device)"]), ["Device result", res.device_result ?? "", "", "measured (device)"],
      ...res.metrics.map((m) => [m.label, String(m.value ?? ""), m.unit, m.valid ? "calculated" : "calculated (unreliable)"])];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(",")).join("\n")], { type: "text/csv" }));
    a.download = "wetcor_arduino_rig_results.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const v = res?.device_verdict;
  const banner = v === "healthy" ? { Icon: ShieldCheck, cls: "border-good/50 bg-good-soft", ink: "text-good" } : v === "corroded" ? { Icon: ShieldAlert, cls: "border-bad/50 bg-bad-soft", ink: "text-bad" } : { Icon: ShieldQuestion, cls: "border-line-2 bg-panel-2", ink: "text-ink-2" };
  const rates = KEY_RATES.map((n) => res?.metrics.find((m) => m.name === n)).filter(Boolean) as Metric[];
  const others = (res?.metrics ?? []).filter((m) => !KEY_RATES.includes(m.name));
  const faraday = res?.metrics.find((m) => m.name === "rig_faraday_rate");

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)]">
      <div className="flex min-w-0 flex-col gap-5 print:hidden">
        <Card title="1 · Paste the Arduino output" actions={<Button size="sm" variant="ghost" icon={<ClipboardPaste className="size-3.5" />} onClick={() => setText(EXAMPLE)}>Use example test</Button>}>
          <Textarea aria-label="Arduino Serial Monitor output" rows={11} className="font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"Copy from the Arduino IDE Serial Monitor and paste here.\n\nGood ACS712 AO: 2.527 V\nCorroded ACS712 AO: 2.528 V\nGood current: 0.145 A\n...\nRESULT: HEALTHY ELECTRODE"} />
          <p className="mt-2 text-xs text-muted">Several cycles can be pasted together: they are averaged and the real scatter is measured. Timestamps are ignored.</p>
          {err && <div className="mt-3"><Alert tone="bad" title="Could not read this">{err}</Alert></div>}
          {parsed?.warnings.map((w) => <div key={w} className="mt-2"><Alert tone="warn">{w}</Alert></div>)}
          {!!parsed?.unrecognised_lines.length && (
            <details className="mt-2 text-xs text-muted"><summary className="cursor-pointer">{parsed.unrecognised_lines.length} line(s) not used</summary>
              <pre className="mt-1 whitespace-pre-wrap font-mono text-[11px]">{parsed.unrecognised_lines.join("\n")}</pre></details>
          )}
        </Card>
        <Card title="2 · Values (or type them in)" actions={parsed && parsed.n_cycles > 1 ? <Badge tone="accent">{parsed.n_cycles} cycles averaged</Badge> : undefined}>
          <div className="grid gap-3 sm:grid-cols-2">
            {FIELDS.map(([k, label, u]) => (
              <LabeledInput key={k} label={`${label} (${u})`} type="number" step="any" required={k === "good_current_a" || k === "corroded_current_a"} value={vals[k] ?? ""}
                onChange={(e) => { edited.current = true; setVals({ ...vals, [k]: e.target.value }); }} />
            ))}
            <div className="sm:col-span-2"><LabeledInput label="Device result" value={verdictText} placeholder="HEALTHY ELECTRODE" onChange={(e) => setVerdictText(e.target.value)} /></div>
          </div>
        </Card>
        <Card title="3 · Specimen (needed for the corrosion rate)">
          <div className="flex flex-col gap-3">
            <LabeledInput label="Exposed electrode area (cm²)" type="number" min={0} step="any" value={setup.area ?? ""} onChange={(e) => set("area", e.target.value)} hint="The wetted area of the corroded electrode. Remembered on this device." />
            <Field label="Material">
              <Select aria-label="Material" value={setup.profile ?? ""} onChange={(e) => set("profile", e.target.value)}>
                <option value="">Custom values</option>
                {(materials.data ?? []).map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </Select>
            </Field>
            {setup.profile ? <p className="text-xs text-muted">{materials.data?.find((m) => m.key === setup.profile)?.source}</p> : (
              <div className="grid gap-3 sm:grid-cols-2">
                <LabeledInput label="Equivalent weight (g/eq)" type="number" step="any" value={setup.ew ?? ""} onChange={(e) => set("ew", e.target.value)} />
                <LabeledInput label="Density (g/cm³)" type="number" step="any" value={setup.rho ?? ""} onChange={(e) => set("rho", e.target.value)} />
                <div className="sm:col-span-2"><LabeledInput label="Source of these values" value={setup.source ?? ""} onChange={(e) => set("source", e.target.value)} placeholder="e.g. ASTM G102, supplier certificate" /></div>
              </div>
            )}
            <details className="rounded-md border border-line px-3 py-2">
              <summary className="cursor-pointer text-sm text-ink-2">Weight-loss check (most reliable corrosion rate for this rig)</summary>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <LabeledInput label="Mass before (g)" type="number" step="any" value={setup.m0 ?? ""} onChange={(e) => set("m0", e.target.value)} />
                <LabeledInput label="Mass after (g)" type="number" step="any" value={setup.m1 ?? ""} onChange={(e) => set("m1", e.target.value)} />
                <LabeledInput label="Exposure (hours)" type="number" step="any" value={setup.hours ?? ""} onChange={(e) => set("hours", e.target.value)} />
              </div>
              <p className="mt-2 text-xs text-muted">Weigh the cleaned specimen before and after the test. Uses the ASTM G31 weight-loss formula.</p>
            </details>
            <details className="rounded-md border border-line px-3 py-2">
              <summary className="cursor-pointer text-sm text-ink-2">Sensor calibration (optional)</summary>
              <div className="mt-3 grid gap-3 sm:grid-cols-3">
                <LabeledInput label="Good AO at zero current (V)" type="number" step="any" value={setup.zero_good ?? ""} onChange={(e) => set("zero_good", e.target.value)} />
                <LabeledInput label="Corroded AO at zero current (V)" type="number" step="any" value={setup.zero_corroded ?? ""} onChange={(e) => set("zero_corroded", e.target.value)} />
                <LabeledInput label="Sensitivity (V/A)" type="number" step="any" value={setup.sens ?? ""} onChange={(e) => set("sens", e.target.value)} hint="Blank = detected" />
              </div>
            </details>
          </div>
        </Card>
      </div>

      <div className="flex min-w-0 flex-col gap-5">
        {!res ? (
          <Card title="Result"><p className="text-sm text-muted">Paste the Arduino output, or type at least the good and corroded currents. Results appear here straight away.</p></Card>
        ) : (
          <>
            <section className={cx("rounded-lg border p-5", banner.cls)} aria-label="Corrosion verdict">
              <div className="flex items-start gap-3">
                <banner.Icon className={cx("mt-0.5 size-7 shrink-0", banner.ink)} aria-hidden />
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2 text-xs text-ink-2">Device result <OriginBadge origin="measured" />
                    {res.agrees_with_device === true && <Badge tone="good">WETCOR check agrees</Badge>}
                    {res.agrees_with_device === false && <Badge tone="warn">WETCOR check disagrees</Badge>}
                  </div>
                  <div className={cx("mt-1 text-2xl font-semibold tracking-tight", banner.ink)}>{res.device_result || "No device result entered"}</div>
                  <p className="mt-1.5 text-sm text-ink-2">{res.comparison_text}</p>
                </div>
              </div>
            </section>

            <div className="grid gap-3 sm:grid-cols-3">
              {[["Good electrode", `${(res.currents.good_a * 1000).toFixed(1)} mA`, "measured"], ["Corroded electrode", `${(res.currents.corroded_a * 1000).toFixed(1)} mA`, "measured"],
                ["Difference", `${res.currents.delta_a >= 0 ? "+" : ""}${(res.currents.delta_a * 1000).toFixed(1)} mA${res.currents.delta_percent != null ? ` (${res.currents.delta_percent >= 0 ? "+" : ""}${res.currents.delta_percent.toFixed(1)}%)` : ""}`, "calculated"]].map(([k, val, origin]) => (
                <div key={k} className="rounded-lg border border-line bg-panel px-4 py-3">
                  <div className="text-[11px] uppercase tracking-wider text-muted">{k}</div>
                  <div className="num mt-1 text-xl font-semibold">{val}</div>
                  <div className="mt-1.5"><OriginBadge origin={origin} /></div>
                </div>
              ))}
            </div>

            <Card title="Corrosion rate" actions={res.severity && <Badge tone={res.severity.label === "low" ? "good" : res.severity.label === "moderate" ? "warn" : "bad"}>{res.severity.label} ({res.severity.basis})</Badge>}>
              {res.needs.length > 0 && !rates.length ? <Alert tone="info">Enter the {res.needs.join(" and ")} in step 3 to calculate the corrosion rate.</Alert> : (
                <div className="flex flex-col gap-3">
                  <div className="grid gap-3 sm:grid-cols-2">
                    {rates.map((m) => {
                      const lo = m.parameters.range_low_mm_y as number | null | undefined, hi = m.parameters.range_high_mm_y as number | null | undefined;
                      return (
                        <div key={m.name} className={cx("rounded-lg border px-4 py-3", m.name === "rig_gravimetric_rate" ? "border-accent/60 bg-accent-soft/30" : "border-line bg-panel-2")}>
                          <div className="text-xs text-ink-2">{m.label}</div>
                          <div className="num mt-1 text-2xl font-semibold">{fmtNum(m.value)} <span className="text-sm font-normal text-ink-2">{unit(m.unit)}</span></div>
                          {lo != null && hi != null && <div className="num text-xs text-muted">range {fmtNum(lo, 3)} to {fmtNum(hi, 3)} {unit(m.unit)}</div>}
                          <div className="mt-1.5"><OriginBadge origin={m.origin} /></div>
                        </div>
                      );
                    })}
                  </div>
                  {others.length > 0 && (
                    <Table head={["Other results", "Value", "Formula", "Status"]}>
                      {others.map((m) => (
                        <tr key={m.name}><td className="whitespace-normal! text-ink">{m.label}</td><td className="num font-semibold">{fmtNum(m.value)} {unit(m.unit)}</td>
                          <td className="min-w-40 whitespace-normal! font-mono text-[11px] text-ink-2">{m.formula}</td><td>{m.valid ? <Badge tone="good">valid</Badge> : <Badge tone="warn" title={m.warnings.join(" ")}>not resolved</Badge>}</td></tr>
                      ))}
                    </Table>
                  )}
                  {faraday && <p className="text-xs text-muted">The Faraday figure assumes: {faraday.assumptions[0]} {res.severity ? "" : "Add a weight-loss measurement to get a measured rate and a severity class."}</p>}
                </div>
              )}
              {res.warnings.map((w) => <div key={w} className="mt-3"><Alert tone="warn">{w}</Alert></div>)}
            </Card>

            <Card title="How far these numbers can be trusted">
              <ul className="divide-y divide-line text-sm">
                {res.checks.map((c) => (
                  <li key={c.key} className="flex items-start gap-2 py-2">
                    <span className="mt-1.5"><StatusDot status={c.status} /></span>
                    <span className="flex-1 text-ink-2">{c.label}{c.note && <span className="block text-xs text-muted">{c.note}</span>}</span>
                    <span className="num text-right text-ink">{c.value}</span>
                  </li>
                ))}
              </ul>
              {res.notes.map((n) => <div key={n} className="mt-2"><Alert tone="info">{n}</Alert></div>)}
              <p className="mt-3 text-xs text-muted">This rig compares current and voltage; it does not sweep potential, so i_corr, Tafel slopes and R_p are not available from it. For those, upload a potentiostat file in the other tab.</p>
            </Card>

            <div className="flex flex-wrap gap-2 print:hidden">
              <Button icon={<Download className="size-4" />} onClick={csv}>Download results (CSV)</Button>
              <Button variant="ghost" icon={<Printer className="size-4" />} onClick={() => window.print()}>Print / save as PDF</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
