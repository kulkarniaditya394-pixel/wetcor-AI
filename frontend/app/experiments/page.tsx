"use client";

import { Download, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ExperimentForm, SpecimenForm } from "@/components/RecordForms";
import { Badge, Button, Card, DemoBadge, EmptyState, Input, PageHeader, Select, Table, cx } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { apiUrl, type Experiment, type Page, type Specimen } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export default function ExperimentsPage() {
  return <Suspense fallback={null}><Experiments /></Suspense>;
}

function Experiments() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get("tab") === "experiments" ? "experiments" : "specimens";
  const [creating, setCreating] = useState(sp.get("new") === "specimen" || sp.get("new") === "experiment");
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("-created_at");
  const [page, setPage] = useState(1);
  const [demo, setDemo] = useState<"real" | "all" | "demo">("real");
  const [status, setStatus] = useState("");
  const pageSize = 15;
  useEffect(() => { const t = setTimeout(() => { setQuery(q); setPage(1); }, 250); return () => clearTimeout(t); }, [q]);
  useEffect(() => setPage(1), [tab, sort, demo, status]);

  const demoQ = demo === "all" ? "&include_demo=true" : demo === "demo" ? "&demo_only=true" : "";
  const path = `/api/${tab}?page=${page}&page_size=${pageSize}&sort=${sort}${query ? `&q=${encodeURIComponent(query)}` : ""}${demoQ}${tab === "experiments" && status ? `&status=${status}` : ""}`;
  const list = useApi<Page<Specimen | Experiment>>(path);
  const pages = Math.max(1, Math.ceil((list.data?.total ?? 0) / pageSize));
  const setTab = (t: string) => { setCreating(false); router.replace(`/experiments?tab=${t}`); };

  return (
    <>
      <PageHeader eyebrow="Data · Records" title="Experiment Database" subtitle="Specimens, experiments and their linked contact-angle and electrochemical records, stored locally in SQLite."
        actions={<>
          <a href={apiUrl(`/api/exports/${tab}.csv${demo !== "real" ? "?include_demo=true" : ""}`)}><Button variant="ghost" icon={<Download className="size-4" />}>Export CSV</Button></a>
          <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating((c) => !c)}>{tab === "specimens" ? "New specimen" : "New experiment"}</Button>
        </>} />
      <div role="tablist" aria-label="Record type" className="mb-4 flex gap-1 border-b border-line">
        {(["specimens", "experiments"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
            className={cx("-mb-px border-b-2 px-4 py-2 text-sm capitalize", tab === t ? "border-accent font-semibold text-accent" : "border-transparent text-ink-2 hover:text-ink")}>{t}</button>
        ))}
      </div>
      {creating && (
        <Card title={tab === "specimens" ? "Register specimen" : "Create experiment"} className="mb-5">
          {tab === "specimens"
            ? <SpecimenForm onCancel={() => setCreating(false)} onSaved={(s) => router.push(`/experiments/specimens/${s.id}`)} />
            : <ExperimentForm onCancel={() => setCreating(false)} onSaved={(e) => router.push(`/experiments/${e.id}`)} />}
        </Card>
      )}
      <Card pad={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-[220px] flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted" aria-hidden />
            <Input aria-label="Search records" className="pl-8" placeholder={tab === "specimens" ? "Search ID, material, preparation, notes…" : "Search ID, electrolyte, operator, notes…"} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <Select aria-label="Sort" className="w-48" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="-created_at">Newest first</option><option value="created_at">Oldest first</option><option value="code">ID A→Z</option><option value="-code">ID Z→A</option>
            {tab === "specimens" ? <option value="material">Material</option> : <option value="status">Status</option>}
          </Select>
          {tab === "experiments" && (
            <Select aria-label="Status filter" className="w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any status</option><option value="planned">planned</option><option value="in_progress">in progress</option><option value="complete">complete</option><option value="invalid">invalid</option>
            </Select>
          )}
          <Select aria-label="Data source" className="w-44" value={demo} onChange={(e) => setDemo(e.target.value as typeof demo)}>
            <option value="real">Real records only</option><option value="all">Real + demo</option><option value="demo">Demo only</option>
          </Select>
        </div>
        <div className="p-3">
          {list.error ? <div className="text-sm text-bad">{list.error}</div> : list.data && list.data.items.length === 0 ? (
            <EmptyState title={query ? "No matching records" : tab === "specimens" ? "No specimens registered" : "No experiments yet"}
              action={!query && <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setCreating(true)}>{tab === "specimens" ? "Register first specimen" : "Create first experiment"}</Button>}>
              {!query && (tab === "specimens" ? "Every measurement is linked to a specimen. Register the physical specimens you will test." : "An experiment groups the test conditions (electrolyte, temperature, instrument) for a specimen.")}
            </EmptyState>
          ) : tab === "specimens" ? (
            <Table head={["Specimen ID", "Material", "Surface preparation", "Area (cm²)", "Experiments", "CA runs", "EC runs", "Created"]}>
              {(list.data?.items as Specimen[] | undefined)?.map((s) => (
                <tr key={s.id} className="hover:bg-panel-2/60">
                  <td><Link className="font-semibold text-accent hover:underline" href={`/experiments/specimens/${s.id}`}>{s.code}</Link> {s.is_demo && <DemoBadge compact />}</td>
                  <td>{s.material}</td><td className="text-ink-2">{s.surface_preparation ?? "—"}</td><td className="num">{s.exposed_area_cm2 ?? "—"}</td>
                  <td className="num">{s.n_experiments}</td><td className="num">{s.n_contact_angle}</td><td className="num">{s.n_corrosion}</td>
                  <td className="whitespace-nowrap text-xs text-muted">{fmtDate(s.created_at)}</td>
                </tr>
              ))}
            </Table>
          ) : (
            <Table head={["Experiment ID", "Specimen", "Type", "Electrolyte", "T (°C)", "CA", "EC", "Status", "Created"]}>
              {(list.data?.items as Experiment[] | undefined)?.map((e) => (
                <tr key={e.id} className="hover:bg-panel-2/60">
                  <td><Link className="font-semibold text-accent hover:underline" href={`/experiments/${e.id}`}>{e.code}</Link> {e.is_demo && <DemoBadge compact />}</td>
                  <td>{e.specimen_code}</td><td className="text-ink-2">{e.experiment_type}</td>
                  <td>{e.electrolyte ?? "—"}{e.concentration_value != null && ` ${e.concentration_value} ${e.concentration_unit ?? ""}`}</td>
                  <td className="num">{e.temperature_c ?? "—"}</td><td className="num">{e.n_contact_angle}</td><td className="num">{e.n_corrosion}</td>
                  <td><Badge tone={e.status === "complete" ? "good" : e.status === "invalid" ? "bad" : "neutral"}>{e.status.replace("_", " ")}</Badge></td>
                  <td className="whitespace-nowrap text-xs text-muted">{fmtDate(e.created_at)}</td>
                </tr>
              ))}
            </Table>
          )}
          {list.data && list.data.total > pageSize && (
            <nav aria-label="Pagination" className="mt-3 flex items-center justify-end gap-2 text-sm">
              <span className="text-muted">{list.data.total} records · page {page} of {pages}</span>
              <Button size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <Button size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
            </nav>
          )}
        </div>
      </Card>
    </>
  );
}
