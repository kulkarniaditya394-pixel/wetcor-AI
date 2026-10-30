"use client";

import Link from "next/link";
import type { AuditItem, CARun, CorrosionRun } from "@/lib/api";
import { fmtDate, fmtDeg, fmtNum, unit } from "@/lib/format";
import { classTone } from "@/lib/wettability";
import { Badge, EmptyState, OriginBadge, Table } from "./ui";

export function CARunsTable({ runs }: { runs: CARun[] }) {
  if (!runs.length) return <EmptyState title="No contact-angle measurements"><Link className="text-accent underline" href="/wettability">Open the Wettability Lab</Link> to capture one.</EmptyState>;
  return (
    <Table head={["Run", "Measured", "Mean", "L / R", "Class", "Method", "Status"]}>
      {runs.map((r) => (
        <tr key={r.id}>
          <td><Link className="text-accent hover:underline" href={`/wettability/${r.id}`}>CA-{r.id}</Link></td>
          <td className="whitespace-nowrap text-xs text-ink-2">{fmtDate(r.measured_at)}</td>
          <td className="num font-semibold">{fmtDeg(r.mean_deg)}</td>
          <td className="num text-ink-2">{fmtDeg(r.left_deg)} / {fmtDeg(r.right_deg)}</td>
          <td>{r.classification && <Badge tone={classTone(r.classification)}>{r.classification}</Badge>}</td>
          <td className="text-xs">{r.method}</td>
          <td><Badge tone={r.status === "accepted" ? "good" : "bad"}>{r.status}</Badge></td>
        </tr>
      ))}
    </Table>
  );
}

const KEY_METRICS = ["i_corr", "corrosion_rate", "rp", "ocp_mean", "z_mod_low_f"];

export function CorrosionRunsTable({ runs }: { runs: CorrosionRun[] }) {
  if (!runs.length) return <EmptyState title="No electrochemical runs"><Link className="text-accent underline" href="/corrosion">Import a potentiostat file</Link>.</EmptyState>;
  return (
    <Table head={["Run", "Method", "Points", "Key results", "Status"]}>
      {runs.map((r) => {
        const ms = (r.metrics ?? []).filter((m) => KEY_METRICS.includes(m.name));
        return (
          <tr key={r.id}>
            <td><Link className="text-accent hover:underline" href={`/corrosion/runs/${r.id}`}>EC-{r.id}</Link></td>
            <td>{r.method.toUpperCase()}</td>
            <td className="num">{r.n_points}</td>
            <td className="whitespace-normal! text-sm">
              {ms.length ? ms.map((m) => (
                <div key={m.name} className="flex items-center gap-2">
                  <span className="text-ink-2">{m.label}:</span> <span className="num font-semibold">{fmtNum(m.value)} {unit(m.unit)}</span>
                  <OriginBadge origin={m.origin} />{!m.valid && <Badge tone="bad">unreliable</Badge>}
                </div>
              )) : <span className="text-muted">not analysed</span>}
            </td>
            <td><Badge tone={r.analysis_status === "analysed" ? "good" : r.analysis_status === "imported" ? "neutral" : "warn"}>{r.analysis_status.replace("_", " ")}</Badge></td>
          </tr>
        );
      })}
    </Table>
  );
}

export function History({ items }: { items: AuditItem[] }) {
  if (!items.length) return <div className="text-sm text-muted">No recorded events.</div>;
  return (
    <ol className="space-y-2 text-sm">
      {items.map((h) => <li key={h.id} className="border-l-2 border-line-2 pl-3"><div>{h.summary}</div><div className="text-xs text-muted">{h.action} · {fmtDate(h.created_at)}</div></li>)}
    </ol>
  );
}
