"use client";

import { ArrowLeft, Crop, Download, RotateCcw, ScanLine, Wand2, XCircle } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { AnnotationCanvas, type Handles } from "@/components/AnnotationCanvas";
import { CameraPanel } from "@/components/CameraPanel";
import { SpecimenPicker } from "@/components/SpecimenPicker";
import { Alert, Badge, Button, Card, EmptyState, Field, Input, LabeledInput, OriginBadge, PageHeader, Select, StatusDot, Table, Textarea } from "@/components/ui";
import { EngineBanner } from "@/components/EngineBanner";
import { useApi } from "@/hooks/useApi";
import type { Capture } from "@/hooks/useCamera";
import { api, form, type CAResult, type CARun, type Pt } from "@/lib/api";
import { fmtDate, fmtDeg } from "@/lib/format";
import { isStaticDemo } from "@/lib/mode";
import { CA_NOTE, classTone } from "@/lib/wettability";

type Shot = Capture & { source: "camera" | "upload"; filename: string };
type Opts = { mode: "auto" | "manual_tangent"; threshold: number | null; polarity: "auto" | "dark_drop" | "light_drop"; fit_radius_px: number | null; primary_method: "polynomial" | "circle" };


function defaultHandles(w: number, h: number): Handles {
  const y = Math.round(h * 0.72);
  return { baseline: [[w * 0.05, y], [w * 0.95, y]], contact_left: [w * 0.35, y], contact_right: [w * 0.65, y], tangent_left: [w * 0.4, y - h * 0.15], tangent_right: [w * 0.6, y - h * 0.15] };
}

function handlesFrom(r: CAResult, w: number, h: number): Handles {
  const g = r.geometry;
  const d = defaultHandles(w, h);
  const b = g.baseline;
  const base: [Pt, Pt] = b && b.length === 2
    ? [[b[0][0] + 0.05 * (b[1][0] - b[0][0]), b[0][1] + 0.05 * (b[1][1] - b[0][1])], [b[1][0] - 0.05 * (b[1][0] - b[0][0]), b[1][1] - 0.05 * (b[1][1] - b[0][1])]]
    : d.baseline;
  return {
    baseline: base,
    contact_left: g.contact_left ?? d.contact_left,
    contact_right: g.contact_right ?? d.contact_right,
    tangent_left: g.tangent_left?.[1] ?? d.tangent_left,
    tangent_right: g.tangent_right?.[1] ?? d.tangent_right,
  };
}

export default function WettabilityPage() {
  const [shot, setShot] = useState<Shot | null>(null);
  const [opts, setOpts] = useState<Opts>({ mode: "auto", threshold: null, polarity: "auto", fit_radius_px: null, primary_method: "polynomial" });
  const [roi, setRoi] = useState<[number, number, number, number] | null>(null);
  const [roiDrawing, setRoiDrawing] = useState(false);
  const [handles, setHandles] = useState<Handles | null>(null);
  const [corrected, setCorrected] = useState(false);
  const [result, setResult] = useState<CAResult | null>(null);
  const [autoResult, setAutoResult] = useState<CAResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const hosted = isStaticDemo();
  const recent = useApi<CARun[]>(hosted ? null : "/api/wettability/measurements?limit=8");

  const params = useCallback((o: Opts, h: Handles | null, corr: boolean, r: typeof roi) => {
    const p: Record<string, unknown> = { mode: o.mode, polarity: o.polarity, primary_method: o.primary_method };
    if (r) p.roi = r;
    if (o.threshold !== null) p.threshold = o.threshold;
    if (o.fit_radius_px) p.fit_radius_px = o.fit_radius_px;
    if (h && (corr || o.mode === "manual_tangent")) {
      p.baseline = h.baseline;
      p.contact_left = h.contact_left;
      p.contact_right = h.contact_right;
      if (o.mode === "manual_tangent") Object.assign(p, { tangent_left: h.tangent_left, tangent_right: h.tangent_right });
    }
    return p;
  }, []);

  const analyse = useCallback(async (s: Shot, o: Opts, h: Handles | null, corr: boolean, r: typeof roi) => {
    setBusy(true);
    setErr(null);
    try {
      const res = await api<CAResult>("/api/wettability/analyze", { method: "POST", body: form({ image: [s.blob, s.filename], params: JSON.stringify(params(o, h, corr, r)) }) });
      setResult(res);
      if (!res.manual_correction && o.mode === "auto") setAutoResult(res);
      else if (res.auto_result) setAutoResult((a) => a ?? res.auto_result!);
      if (!corr && o.mode === "auto") setHandles(handlesFrom(res, s.width, s.height));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [params]);

  const onCapture = (s: Shot) => {
    if (shot && shot.url !== s.url) URL.revokeObjectURL(shot.url);
    const o = { ...opts, mode: "auto" as const };
    setShot(s); setOpts(o); setRoi(null); setCorrected(false); setResult(null); setAutoResult(null); setHandles(null);
    analyse(s, o, null, false, null);
  };

  const discard = () => {
    if (shot) URL.revokeObjectURL(shot.url);
    setShot(null); setResult(null); setAutoResult(null); setHandles(null); setRoi(null); setCorrected(false);
  };

  useEffect(() => () => { if (shot) URL.revokeObjectURL(shot.url); }, [shot]);

  return (
    <>
      <PageHeader eyebrow="Instrument · Contact angle" title="Wettability Lab" subtitle={hosted ? "Upload a droplet photo or use your camera: the contact angle is measured in your browser and the surface is classed hydrophilic or hydrophobic." : "Sessile-drop water contact angle from a USB camera: capture, automatic geometric analysis, manual correction and traceable saving."} />
      <EngineBanner />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.7fr)_minmax(340px,1fr)]">
        <div className="flex min-w-0 flex-col gap-5">
          <div className={shot ? "hidden" : ""}>
            <Card title="Live camera">
              <CameraPanel onCapture={onCapture} busy={busy} />
            </Card>
          </div>
          {shot && (
            <Card title="Analysis workspace" actions={
              <>
                <Badge>{shot.width}×{shot.height}</Badge>
                <Badge tone={shot.source === "camera" ? "good" : "neutral"}>{shot.source === "camera" ? "Captured frame" : "Uploaded image"}</Badge>
              </>
            }>
              <div className="flex flex-col gap-3">
                <AnnotationCanvas
                  src={shot.url} width={shot.width} height={shot.height} geometry={result?.geometry} handles={handles} mode={opts.mode}
                  onHandlesChange={(h) => { setHandles(h); setCorrected(true); }}
                  roi={roi} roiDrawing={roiDrawing} onRoi={(r) => { setRoi(r); setRoiDrawing(false); }}
                  labels={result?.mean_deg != null ? { left: `θL ${fmtDeg(result.left_deg)}`, right: `θR ${fmtDeg(result.right_deg)}` } : undefined}
                />
                <p className="text-xs text-muted">
                  <span className="text-accent">●</span> baseline · <span className="text-warn">●</span> contact points · <span className="text-pred">●</span> tangent points (manual tangent mode) ·
                  <span className="text-good"> —</span> detected boundary · drag handles or focus one and use the arrow keys.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" icon={<ScanLine className="size-4" />} busy={busy} onClick={() => analyse(shot, opts, handles, corrected, roi)}>
                    {corrected || opts.mode === "manual_tangent" ? "Re-analyse with corrections" : "Re-analyse"}
                  </Button>
                  <Button icon={<Crop className="size-4" />} variant={roiDrawing ? "primary" : "secondary"} onClick={() => setRoiDrawing((d) => !d)}>
                    {roiDrawing ? "Drag a rectangle…" : roi ? "Redraw ROI" : "Select ROI"}
                  </Button>
                  {roi && <Button variant="ghost" onClick={() => { setRoi(null); analyse(shot, opts, handles, corrected, null); }}>Clear ROI</Button>}
                  <Button variant="ghost" icon={<RotateCcw className="size-4" />} onClick={() => { const o = { ...opts, mode: "auto" as const, threshold: null, polarity: "auto" as const, fit_radius_px: null }; setOpts(o); setCorrected(false); analyse(shot, o, null, false, roi); }}>
                    Reset to automatic
                  </Button>
                  <div className="flex-1" />
                  <Button variant="ghost" icon={<ArrowLeft className="size-4" />} onClick={discard}>Back to live camera</Button>
                </div>
                <details className="rounded-md border border-line bg-panel-2/50 px-3 py-2">
                  <summary className="cursor-pointer text-sm font-medium text-ink-2">Analysis settings</summary>
                  <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                    <Field label="Mode">
                      <Select value={opts.mode} aria-label="Analysis mode" onChange={(e) => { const mode = e.target.value as Opts["mode"]; setOpts({ ...opts, mode }); if (mode === "manual_tangent" && !handles) setHandles(defaultHandles(shot.width, shot.height)); }}>
                        <option value="auto">Automatic / corrected fit</option>
                        <option value="manual_tangent">Manual tangent (operator points)</option>
                      </Select>
                    </Field>
                    <Field label="Reported method">
                      <Select value={opts.primary_method} aria-label="Reported fit method" onChange={(e) => setOpts({ ...opts, primary_method: e.target.value as Opts["primary_method"] })}>
                        <option value="polynomial">Local tangent (polynomial)</option>
                        <option value="circle">Spherical-cap circle fit</option>
                      </Select>
                    </Field>
                    <Field label="Droplet polarity">
                      <Select value={opts.polarity} aria-label="Droplet polarity" onChange={(e) => setOpts({ ...opts, polarity: e.target.value as Opts["polarity"] })}>
                        <option value="auto">Auto</option><option value="dark_drop">Dark drop on light</option><option value="light_drop">Light drop on dark</option>
                      </Select>
                    </Field>
                    <LabeledInput label="Threshold (0–255)" type="number" min={0} max={255} placeholder={`Otsu ${result?.params?.threshold_used ?? ""}`}
                      value={opts.threshold ?? ""} onChange={(e) => setOpts({ ...opts, threshold: e.target.value === "" ? null : Number(e.target.value) })} />
                    <LabeledInput label="Fit radius (px)" type="number" min={5} placeholder={`auto ${result?.geometry?.fit_radius_px ?? ""}`}
                      value={opts.fit_radius_px ?? ""} onChange={(e) => setOpts({ ...opts, fit_radius_px: e.target.value === "" ? null : Number(e.target.value) })} />
                  </div>
                  <p className="mt-2 text-xs text-muted">Changing threshold, polarity or fit radius counts as a manual correction and is recorded as <code>manual_corrected</code>.</p>
                </details>
              </div>
            </Card>
          )}
          {!shot && !hosted && <RecentMeasurements runs={recent.data} loading={recent.loading} error={recent.error} />}
        </div>

        <div className="flex min-w-0 flex-col gap-5">
          {err && <Alert tone="bad" title="Analysis request failed">{err}</Alert>}
          {shot ? (
            <>
              <ResultPanel result={result} auto={autoResult} busy={busy} />
              {hosted ? <HostedActions result={result} filename={shot.filename} onDiscard={discard} /> : <SavePanel shot={shot} result={result} params={params(opts, handles, corrected, roi)} onSaved={() => { recent.reload(); }} onDiscard={discard} />}
            </>
          ) : (
            <Card title="Procedure">
              <ol className="list-decimal space-y-2 pl-5 text-sm text-ink-2">
                <li>Level the specimen; align the camera horizontally with its surface and back-light the droplet.</li>
                <li>Press <strong>Start camera</strong>, choose the USB camera and resolution, and focus on the droplet profile.</li>
                <li>Dispense the droplet, then press <strong>Capture &amp; Analyse</strong>. The frame is frozen and analysed locally.</li>
                <li>Check the baseline, contact points and boundary. Drag handles or set an ROI and re-analyse if needed.</li>
                <li>Link the result to a specimen and save. The original image is stored unmodified with its SHA-256 hash.</li>
              </ol>
              <p className="mt-4 border-t border-line pt-3 text-xs text-muted">{CA_NOTE}</p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function ResultPanel({ result, auto, busy }: { result: CAResult | null; auto: CAResult | null; busy: boolean }) {
  if (!result) return <Card title="Result"><div className="text-sm text-muted">{busy ? "Analysing captured frame…" : "No analysis yet."}</div></Card>;
  const statusTone = result.status === "ok" ? "good" : result.status === "needs_correction" ? "warn" : "bad";
  const cls = result.classification;
  return (
    <Card title="Result" actions={<Badge tone={statusTone}>{result.status.replace("_", " ")}</Badge>}>
      {result.mean_deg != null ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-xs text-muted">Mean contact angle <OriginBadge origin="measured" /></div>
              <div className="num text-4xl font-semibold text-ink" data-testid="mean-angle">{fmtDeg(result.mean_deg)}</div>
            </div>
            {cls && <Badge tone={classTone(cls.label)} className="text-xs normal-case tracking-normal">{cls.text}</Badge>}
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[["Left θL", fmtDeg(result.left_deg)], ["Right θR", fmtDeg(result.right_deg)], ["|L − R|", fmtDeg(result.lr_diff_deg)]].map(([k, v]) => (
              <div key={k} className="rounded-md border border-line bg-panel-2 py-2"><div className="text-[11px] text-muted">{k}</div><div className="num text-lg font-semibold">{v}</div></div>
            ))}
          </div>
          {cls?.recommend_repeat && <Alert tone="warn" title="Classification uncertain — repeat the measurement">{cls.reasons.join(" ") || "Value at the 90° boundary."}</Alert>}
          <div className="text-xs text-muted">Method <code className="text-ink-2">{result.method}</code> · algorithm {result.algorithm_version}{result.methods?.circle?.angle_deg != null && <> · circle fit {fmtDeg(result.methods.circle.angle_deg)} ({result.methods.circle.status})</>}</div>
          {result.manual_correction && auto?.mean_deg != null && (
            <div className="rounded-md border border-line bg-panel-2 px-3 py-2 text-sm">
              <div className="text-xs font-semibold uppercase tracking-wider text-muted">Automatic vs corrected</div>
              <div className="num mt-1">Automatic {fmtDeg(auto.mean_deg)} → corrected {fmtDeg(result.mean_deg)} <span className="text-muted">(Δ {fmtDeg((result.mean_deg ?? 0) - auto.mean_deg)})</span></div>
              <div className="text-xs text-muted">The automatic result is stored separately when you save.</div>
            </div>
          )}
        </div>
      ) : (
        <Alert tone="bad" title="No reliable angle">{result.errors.join(" ")} Adjust the ROI, threshold or baseline, or switch to manual tangent mode.</Alert>
      )}
      {result.warnings.length > 0 && <div className="mt-3 flex flex-col gap-1.5">{result.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}</div>}
      <h3 className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wider text-muted">Quality diagnostics</h3>
      <ul className="divide-y divide-line rounded-md border border-line text-sm">
        {result.diagnostics.map((d) => (
          <li key={d.key} className="flex items-start gap-2 px-3 py-1.5">
            <span className="mt-1.5"><StatusDot status={d.status} /></span>
            <span className="flex-1 text-ink-2">{d.label}{d.note && <span className="block text-xs text-muted">{d.note}</span>}</span>
            <span className="num text-ink">{String(d.value)} {d.unit}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">{result.uncertainty_note}</p>
      {result.overlay_png_base64 && (
        <a className="mt-3 inline-flex items-center gap-1.5 text-sm text-accent hover:underline" download="wetcor_annotated_overlay.png" href={`data:image/png;base64,${result.overlay_png_base64}`}>
          <Download className="size-4" /> Download annotated overlay
        </a>
      )}
      <p className="mt-4 border-t border-line pt-3 text-xs text-muted">{CA_NOTE}</p>
    </Card>
  );
}

function SavePanel({ shot, result, params, onSaved, onDiscard }: { shot: Shot; result: CAResult | null; params: Record<string, unknown>; onSaved: () => void; onDiscard: () => void }) {
  const [specimenId, setSpecimenId] = useState<number | null>(null);
  const [experimentId, setExperimentId] = useState<number | null>(null);
  const [liquid, setLiquid] = useState("Deionised water");
  const [volume, setVolume] = useState("");
  const [notes, setNotes] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "good" | "bad"; text: string; id?: number } | null>(null);
  const [touched, setTouched] = useState(false);
  const canAccept = !!result && result.mean_deg != null;
  useEffect(() => setMsg(null), [shot]);

  const save = async (status: "accepted" | "rejected") => {
    setTouched(true);
    if (!specimenId) return;
    if (status === "rejected" && !reason.trim()) return;
    setBusy(true);
    try {
      const meta = { specimen_id: specimenId, experiment_id: experimentId, liquid, droplet_volume_ul: volume ? Number(volume) : null, notes: notes || null,
        captured_at: shot.capturedAt, status, rejection_reason: status === "rejected" ? reason : null };
      const run = await api<CARun>("/api/wettability/measurements", { method: "POST", body: form({ image: [shot.blob, shot.filename], params: JSON.stringify(params), meta: JSON.stringify(meta) }) });
      setMsg({ tone: "good", text: status === "accepted" ? `Saved CA-${run.id}: ${fmtDeg(run.mean_deg)} (${run.method}).` : `Saved CA-${run.id} as rejected.`, id: run.id });
      setRejecting(false);
      onSaved();
    } catch (e) {
      setMsg({ tone: "bad", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  const volId = "ca-volume";
  return (
    <Card title="Save measurement">
      <div className="flex flex-col gap-3">
        <SpecimenPicker specimenId={specimenId} experimentId={experimentId} onChange={(s, e) => { setSpecimenId(s); setExperimentId(e); }}
          error={touched && !specimenId ? "Select the specimen this droplet was measured on." : undefined} />
        <div className="grid gap-3 sm:grid-cols-2">
          <LabeledInput label="Droplet liquid" value={liquid} onChange={(e) => setLiquid(e.target.value)} required />
          <Field label="Droplet volume (µL)" htmlFor={volId} hint="Leave blank if not known."><Input id={volId} type="number" min={0} step="0.1" value={volume} onChange={(e) => setVolume(e.target.value)} /></Field>
        </div>
        <Field label="Notes"><Textarea aria-label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Ambient conditions, dispensing method, droplet age…" /></Field>
        <div className="text-xs text-muted">Captured {fmtDate(shot.capturedAt)} · {shot.deviceLabel}</div>
        {msg && <Alert tone={msg.tone}>{msg.text} {msg.id && <Link className="underline" href={`/wettability/${msg.id}`}>Open record</Link>}</Alert>}
        {!rejecting ? (
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" icon={<Wand2 className="size-4" />} disabled={!canAccept} busy={busy} onClick={() => save("accepted")}
              title={canAccept ? undefined : "No reliable angle to accept"}>Save measurement</Button>
            <Button variant="danger" icon={<XCircle className="size-4" />} onClick={() => setRejecting(true)}>Reject image…</Button>
            <Button variant="ghost" onClick={onDiscard}>Discard</Button>
          </div>
        ) : (
          <div className="flex flex-col gap-2 rounded-md border border-bad/40 p-3">
            <LabeledInput label="Rejection reason" required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. droplet not settled, glare at contact line"
              error={touched && !reason.trim() ? "A reason is required." : undefined} />
            <div className="flex gap-2">
              <Button variant="danger" busy={busy} onClick={() => save("rejected")}>Save as rejected</Button>
              <Button variant="ghost" onClick={() => setRejecting(false)}>Cancel</Button>
            </div>
            <p className="text-xs text-muted">Rejected images are kept for traceability and excluded from datasets.</p>
          </div>
        )}
      </div>
    </Card>
  );
}

function RecentMeasurements({ runs, loading, error }: { runs: CARun[] | null; loading: boolean; error: string | null }) {
  const rows = useMemo(() => runs ?? [], [runs]);
  return (
    <Card title="Recent measurements" actions={<Link href="/experiments" className="text-xs text-accent hover:underline">All records</Link>}>
      {error ? <Alert tone="bad">{error}</Alert> : loading ? <div className="text-sm text-muted">Loading…</div> : rows.length === 0 ? (
        <EmptyState title="No contact-angle measurements yet">Start the camera and capture a droplet, or upload an existing image.</EmptyState>
      ) : (
        <Table head={["Run", "Measured", "Mean", "L / R", "Class", "Method", "Status"]}>
          {rows.map((r) => (
            <tr key={r.id} className="hover:bg-panel-2/60">
              <td><Link className="text-accent hover:underline" href={`/wettability/${r.id}`}>CA-{r.id}</Link></td>
              <td className="whitespace-nowrap text-ink-2">{fmtDate(r.measured_at)}</td>
              <td className="num font-semibold">{fmtDeg(r.mean_deg)}</td>
              <td className="num text-ink-2">{fmtDeg(r.left_deg)} / {fmtDeg(r.right_deg)}</td>
              <td>{r.classification && <Badge tone={classTone(r.classification)}>{r.classification}</Badge>}</td>
              <td className="text-xs text-ink-2">{r.method}</td>
              <td><Badge tone={r.status === "accepted" ? "good" : "bad"}>{r.status}</Badge></td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

/** Hosted site: nothing is stored; offer the result as a download instead of the database save form. */
function HostedActions({ result, filename, onDiscard }: { result: CAResult | null; filename: string; onDiscard: () => void }) {
  const download = () => {
    if (!result) return;
    const { overlay_png_base64: _overlay, ...rest } = result;
    const blob = new Blob([JSON.stringify({ file: filename, analysed_in: "browser (WETCOR AI hosted engine)", origin: "measured", ...rest }, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `wetcor_contact_angle_${filename.replace(/.[^.]+$/, "")}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <Card title="Keep this result">
      <p className="text-sm text-ink-2">This hosted site does not store records. Download the values and diagnostics, or use the annotated overlay link above. Saving measurements to a specimen database is available in the local app.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="primary" icon={<Download className="size-4" />} disabled={!result || result.mean_deg == null} onClick={download}>Download result (JSON)</Button>
        <Button variant="ghost" onClick={onDiscard}>Analyse another image</Button>
      </div>
    </Card>
  );
}
