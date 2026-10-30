"use client";

import { Download, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { CARunsTable, CorrosionRunsTable, History } from "@/components/LinkedRecords";
import { ExperimentForm } from "@/components/RecordForms";
import { Alert, Badge, Button, Card, DemoBanner, EmptyState, KV, LabeledInput, PageHeader, Spinner, Table } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api, apiUrl, type AuditItem, type CARun, type CorrosionRun, type Experiment, type Specimen } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Detail = { specimen: Specimen; experiments: Experiment[]; contact_angle_runs: CARun[]; corrosion_runs: CorrosionRun[];
  artifacts: { id: number; kind: string; original_filename: string; sha256: string; size_bytes: number; created_at: string }[]; history: AuditItem[] };

export default function SpecimenPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data, error, loading, reload } = useApi<Detail>(`/api/specimens/${id}`);
  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [newExp, setNewExp] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [msg, setMsg] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  if (loading && !data) return <Spinner />;
  if (error || !data) return <Alert tone="bad" title="Could not load specimen">{error}</Alert>;
  const s = data.specimen;
  const fields: [keyof Specimen, string, string?][] = [["material", "Material"], ["surface_preparation", "Surface preparation"], ["dimensions", "Dimensions"],
    ["exposed_area_cm2", "Exposed area (cm²)", "number"], ["roughness_ra_um", "Roughness Ra (µm)", "number"], ["batch_source", "Batch / source"], ["notes", "Notes"]];

  return (
    <>
      <PageHeader eyebrow="Experiments · Specimen" title={`Specimen ${s.code}`} subtitle={`${s.material} · registered ${fmtDate(s.created_at)}`}
        actions={<>{!s.is_demo && <Button icon={<Pencil className="size-4" />} onClick={() => { setEditing(!editing); setEdit(Object.fromEntries(fields.map(([k]) => [k, s[k] == null ? "" : String(s[k])]))); }}>Edit</Button>}</>} />
      {s.is_demo && <DemoBanner />}
      {msg && <div className="mb-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
        <div className="flex flex-col gap-5">
          <Card title="Specimen record">
            {editing ? (
              <form className="flex flex-col gap-3" onSubmit={async (e) => {
                e.preventDefault();
                const body: Record<string, unknown> = {};
                for (const [k, , t] of fields) body[k] = edit[k as string] === "" ? null : t === "number" ? Number(edit[k as string]) : edit[k as string];
                if (!body.material) return setMsg({ tone: "bad", text: "Material is required." });
                try { await api(`/api/specimens/${s.id}`, { method: "PATCH", json: body }); setEditing(false); setMsg({ tone: "good", text: "Specimen updated (change recorded in history)." }); reload(); }
                catch (ex) { setMsg({ tone: "bad", text: (ex as Error).message }); }
              }}>
                {fields.map(([k, label, t]) => <LabeledInput key={k} label={label} type={t ?? "text"} step="any" value={edit[k as string] ?? ""} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} />)}
                <div className="flex gap-2"><Button type="submit" variant="primary">Save</Button><Button type="button" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button></div>
              </form>
            ) : (
              <KV items={fields.map(([k, label]) => [label, s[k] as string | number | null])} />
            )}
          </Card>
          <Card title="Stored files">
            {data.artifacts.length === 0 ? <div className="text-sm text-muted">No files.</div> : (
              <ul className="divide-y divide-line text-sm">
                {data.artifacts.map((a) => (
                  <li key={a.id} className="flex items-center gap-2 py-1.5">
                    <Badge>{a.kind.replace("_", " ")}</Badge>
                    <span className="min-w-0 flex-1 truncate" title={`SHA-256 ${a.sha256}`}>{a.original_filename}</span>
                    <a className="text-accent" aria-label={`Download ${a.original_filename}`} href={apiUrl(`/api/artifacts/${a.id}/download`)}><Download className="size-4" /></a>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="History"><History items={data.history} /></Card>
          {!s.is_demo && (
            <Card title="Delete specimen">
              <p className="text-sm text-muted">Only possible when no experiments, measurements or files are linked. Raw measurements are never cascade-deleted. Type <code>{s.code}</code> to confirm.</p>
              <div className="mt-2 flex gap-2">
                <input aria-label="Confirm specimen ID" className="h-8 w-40 rounded border border-line-2 bg-bg px-2 text-sm" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                <Button size="sm" variant="danger" icon={<Trash2 className="size-3.5" />} disabled={confirm !== s.code}
                  onClick={async () => { try { await api(`/api/specimens/${s.id}?confirm=${encodeURIComponent(s.code)}`, { method: "DELETE" }); router.push("/experiments"); } catch (e) { setMsg({ tone: "bad", text: (e as Error).message }); } }}>Delete</Button>
              </div>
            </Card>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-5">
          <Card title="Experiments" actions={!s.is_demo && <Button size="sm" onClick={() => setNewExp(!newExp)}>New experiment</Button>}>
            {newExp && <div className="mb-4 rounded-md border border-line p-3"><ExperimentForm specimenId={s.id} onCancel={() => setNewExp(false)} onSaved={(e) => router.push(`/experiments/${e.id}`)} /></div>}
            {data.experiments.length === 0 ? <EmptyState title="No experiments for this specimen" /> : (
              <Table head={["Experiment", "Type", "Electrolyte", "T (°C)", "Status"]}>
                {data.experiments.map((e) => (
                  <tr key={e.id}><td><Link className="text-accent hover:underline" href={`/experiments/${e.id}`}>{e.code}</Link></td><td>{e.experiment_type}</td>
                    <td>{e.electrolyte ?? "—"}</td><td className="num">{e.temperature_c ?? "—"}</td><td><Badge>{e.status.replace("_", " ")}</Badge></td></tr>
                ))}
              </Table>
            )}
          </Card>
          <Card title="Contact-angle measurements"><CARunsTable runs={data.contact_angle_runs} /></Card>
          <Card title="Electrochemical runs"><CorrosionRunsTable runs={data.corrosion_runs} /></Card>
        </div>
      </div>
    </>
  );
}
