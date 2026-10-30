"use client";

import { Download, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { Alert, Badge, Button, Card, DemoBanner, KV, OriginBadge, PageHeader, Select, Spinner, StatusDot, Textarea } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, apiUrl, type AuditItem, type CARun, type Diagnostic } from "@/lib/api";
import { fmtDate, fmtDeg } from "@/lib/format";
import { CA_NOTE, classTone } from "@/lib/wettability";

type Detail = CARun & { image: { id: number; sha256: string; original_filename: string; integrity: string }; history: AuditItem[] };

export default function MeasurementDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: r, error, loading, reload } = useApi<Detail>(`/api/wettability/measurements/${id}`);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const [notes, setNotes] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");

  if (loading && !r) return <Spinner />;
  if (error || !r) return <Alert tone="bad" title="Could not load measurement">{error}</Alert>;
  const diags = (r.diagnostics?.diagnostics ?? []) as Diagnostic[];

  const patch = async (body: Record<string, unknown>, ok: string) => {
    setBusy(true);
    try {
      await api(`/api/wettability/measurements/${id}`, { method: "PATCH", json: body });
      setMsg({ tone: "good", text: ok });
      reload();
    } catch (e) {
      setMsg({ tone: "bad", text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader eyebrow="Wettability Lab · Measurement" title={`Contact-angle measurement CA-${r.id}`} subtitle={<>Specimen <Link className="text-accent hover:underline" href={`/experiments/specimens/${r.specimen_id}`}>#{r.specimen_id}</Link>{r.experiment_id && <> · Experiment <Link className="text-accent hover:underline" href={`/experiments/${r.experiment_id}`}>#{r.experiment_id}</Link></>} · measured {fmtDate(r.measured_at)}</>}
        actions={<Badge tone={r.status === "accepted" ? "good" : "bad"}>{r.status}</Badge>} />
      {r.is_demo && <DemoBanner />}
      {msg && <div className="mb-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Original image" actions={<a className="inline-flex items-center gap-1 text-xs text-accent hover:underline" href={apiUrl(`/api/artifacts/${r.image_artifact_id}/download`)}><Download className="size-3.5" />Download</a>}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={apiUrl(`/api/artifacts/${r.image_artifact_id}/download?inline=true`)} alt={`Original droplet image for CA-${r.id}`} className="w-full rounded border border-line" />
          <div className="mt-2 break-all font-mono text-[11px] text-muted">SHA-256 {r.image.sha256} · {r.image.original_filename}</div>
          {r.image.integrity !== "ok" && <div className="mt-2"><Alert tone="bad" title="Stored file problem">{r.image.integrity}</Alert></div>}
        </Card>
        <Card title="Annotated overlay" actions={r.overlay_artifact_id && <a className="inline-flex items-center gap-1 text-xs text-accent hover:underline" href={apiUrl(`/api/artifacts/${r.overlay_artifact_id}/download`)}><Download className="size-3.5" />Download</a>}>
          {r.overlay_artifact_id
            ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={apiUrl(`/api/artifacts/${r.overlay_artifact_id}/download?inline=true`)} alt={`Annotated overlay for CA-${r.id}`} className="w-full rounded border border-line" />
            : <div className="text-sm text-muted">No overlay (analysis failed).</div>}
        </Card>
        <Card title="Values">
          <div className="mb-3 flex items-center gap-3">
            <div className="num text-3xl font-semibold">{fmtDeg(r.mean_deg)}</div>
            <OriginBadge origin="measured" />
            {r.classification && <Badge tone={classTone(r.classification)}>{r.classification}</Badge>}
          </div>
          <KV items={[
            ["Left / right", `${fmtDeg(r.left_deg)} / ${fmtDeg(r.right_deg)}`],
            ["Method", <code key="m">{r.method}</code>],
            ["Algorithm", r.algorithm_version],
            ["Liquid", r.liquid],
            ["Droplet volume", r.droplet_volume_ul != null ? `${r.droplet_volume_ul} µL` : null],
            ["Captured", fmtDate(r.captured_at)],
            ["Rejection reason", r.rejection_reason],
            ["Automatic result", r.auto_result ? `${fmtDeg((r.auto_result as { mean_deg?: number }).mean_deg ?? null)} (${(r.auto_result as { method?: string }).method ?? "auto"}) — kept separately` : "Same as reported (no correction)"],
          ]} />
          {r.warnings.length > 0 && <div className="mt-3 flex flex-col gap-1.5">{r.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}</div>}
          <p className="mt-3 text-xs text-muted">{CA_NOTE}</p>
        </Card>
        <Card title="Quality diagnostics">
          <ul className="divide-y divide-line text-sm">
            {diags.map((d) => (
              <li key={d.key} className="flex items-start gap-2 py-1.5"><span className="mt-1.5"><StatusDot status={d.status} /></span><span className="flex-1 text-ink-2">{d.label}{d.note && <span className="block text-xs text-muted">{d.note}</span>}</span><span className="num">{String(d.value)} {d.unit}</span></li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-muted">{r.diagnostics?.uncertainty_note}</p>
        </Card>
        {!r.is_demo && (
          <Card title="Review & corrections">
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                <Button busy={busy} onClick={() => patch({ reanalyse_params: { ...r.analysis_params, primary_method: "circle" }, reason: "Report spherical-cap fit" }, "Re-analysed with circle fit.")}>Re-analyse: circle fit</Button>
                <Button busy={busy} onClick={() => patch({ reanalyse_params: { ...r.analysis_params, primary_method: "polynomial" }, reason: "Report local tangent" }, "Re-analysed with local tangent.")}>Re-analyse: local tangent</Button>
                <Select aria-label="Measurement status" value={r.status} className="w-40" onChange={(e) => {
                  const status = e.target.value;
                  const reason = status === "rejected" ? prompt("Reason for rejecting this measurement?") : null;
                  if (status === "rejected" && !reason) return;
                  patch({ status, rejection_reason: reason }, `Status set to ${status}.`);
                }}>
                  <option value="accepted">accepted</option><option value="rejected">rejected</option>
                </Select>
              </div>
              <Textarea aria-label="Notes" value={notes ?? r.notes ?? ""} onChange={(e) => setNotes(e.target.value)} />
              <div><Button size="sm" disabled={notes === null} busy={busy} onClick={() => patch({ notes }, "Notes saved.")}>Save notes</Button></div>
              <div className="border-t border-line pt-3">
                <label className="text-xs text-muted" htmlFor="del-confirm">Delete this measurement (files are moved to data/trash). Type <code>CA-{r.id}</code> to confirm.</label>
                <div className="mt-1 flex gap-2">
                  <input id="del-confirm" className="h-8 w-40 rounded border border-line-2 bg-bg px-2 text-sm" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                  <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} disabled={confirm !== `CA-${r.id}`}
                    onClick={async () => { try { await api(`/api/wettability/measurements/${r.id}?confirm=CA-${r.id}`, { method: "DELETE" }); router.push("/wettability"); } catch (e) { setMsg({ tone: "bad", text: (e as Error).message }); } }}>Delete</Button>
                </div>
              </div>
            </div>
          </Card>
        )}
        <Card title="History" className={r.is_demo ? "" : ""}>
          {r.history.length === 0 ? <div className="text-sm text-muted">No events.</div> : (
            <ol className="space-y-2 text-sm">
              {r.history.map((h) => <li key={h.id} className="border-l-2 border-line-2 pl-3"><div className="text-ink">{h.summary}</div><div className="text-xs text-muted">{h.action} · {fmtDate(h.created_at)}</div></li>)}
            </ol>
          )}
        </Card>
      </div>
    </>
  );
}
