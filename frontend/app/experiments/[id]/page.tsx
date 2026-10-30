"use client";

import { FileText, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { CARunsTable, CorrosionRunsTable, History } from "@/components/LinkedRecords";
import { Alert, Button, Card, DemoBanner, KV, PageHeader, Select, Spinner } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, apiUrl, type AuditItem, type CARun, type CorrosionRun, type Experiment, type Specimen } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Detail = { experiment: Experiment; specimen: Specimen; contact_angle_runs: CARun[]; corrosion_runs: CorrosionRun[]; history: AuditItem[] };

export default function ExperimentPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<Detail>(`/api/experiments/${id}`);
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  if (loading && !data) return <Spinner />;
  if (error || !data) return <Alert tone="bad" title="Could not load experiment">{error}</Alert>;
  const e = data.experiment;
  const complete = data.contact_angle_runs.some((c) => c.status === "accepted") && data.corrosion_runs.length > 0;

  return (
    <>
      <PageHeader eyebrow="Experiments · Experiment" title={`Experiment ${e.code}`}
        subtitle={<>Specimen <Link className="text-accent hover:underline" href={`/experiments/specimens/${data.specimen.id}`}>{data.specimen.code}</Link> ({data.specimen.material}) · {e.experiment_type}</>}
        actions={<a href={apiUrl(`/api/reports/experiment/${e.id}`)} target="_blank" rel="noreferrer"><Button variant="primary" icon={<FileText className="size-4" />}>Experiment report</Button></a>} />
      {e.is_demo && <DemoBanner />}
      {msg && <div className="mb-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <div className="flex flex-col gap-5">
          <Card title="Conditions">
            <KV items={[["Performed", fmtDate(e.performed_at)], ["Operator", e.operator], ["Electrolyte", e.electrolyte],
              ["Concentration", e.concentration_value != null ? `${e.concentration_value} ${e.concentration_unit ?? ""}` : null], ["Temperature", e.temperature_c != null ? `${e.temperature_c} °C` : null],
              ["Instrument", e.instrument], ["Reference electrode", e.reference_electrode], ["Procedure", e.procedure], ["Notes", e.notes]]} />
          </Card>
          <Card title="Record status">
            <div className="flex flex-col gap-2">
              <Select aria-label="Experiment status" value={e.status} disabled={e.is_demo} onChange={async (ev) => {
                try { await api(`/api/experiments/${e.id}`, { method: "PATCH", json: { status: ev.target.value } }); setMsg({ tone: "good", text: `Status set to ${ev.target.value}.` }); reload(); }
                catch (ex) { setMsg({ tone: "bad", text: (ex as Error).message }); }
              }}>
                <option value="planned">planned</option><option value="in_progress">in progress</option><option value="complete">complete</option><option value="invalid">invalid</option>
              </Select>
              <p className="text-xs text-muted">{complete ? "Has an accepted contact angle and at least one electrochemical run." : "A complete record needs an accepted contact-angle measurement and an electrochemical run."}</p>
            </div>
          </Card>
          <Card title="History"><History items={data.history} /></Card>
          {!e.is_demo && (
            <Card title="Delete experiment">
              <p className="text-sm text-muted">Only possible once no measurements are linked. Type <code>{e.code}</code> to confirm.</p>
              <div className="mt-2 flex gap-2">
                <input aria-label="Confirm experiment ID" className="h-8 w-40 rounded border border-line-2 bg-bg px-2 text-sm" value={confirm} onChange={(ev) => setConfirm(ev.target.value)} />
                <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} disabled={confirm !== e.code}
                  onClick={async () => { try { await api(`/api/experiments/${e.id}?confirm=${encodeURIComponent(e.code)}`, { method: "DELETE" }); router.push("/experiments?tab=experiments"); } catch (ex) { setMsg({ tone: "bad", text: (ex as Error).message }); } }}>Delete</Button>
              </div>
            </Card>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <Card title="Contact-angle measurements"><CARunsTable runs={data.contact_angle_runs} /></Card>
          <Card title="Electrochemical runs"><CorrosionRunsTable runs={data.corrosion_runs} /></Card>
        </div>
      </div>
    </>
  );
}
