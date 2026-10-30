"use client";

import { ArrowRight, BrainCircuit, Camera, Database, Droplets, FileUp, Plus, Presentation, Settings2, Zap } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { Alert, Badge, Button, Card, DemoBadge, EmptyState, PageHeader, Spinner, Stat, cx } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { fmtDate } from "@/lib/format";

type Counts = { specimens: number; contact_angle_runs: number; corrosion_runs: number; experiments: number; completed_experiments: number; ml_eligible_records: number };
type Dash = {
  real: Counts; demo: Counts; ml_runs: number;
  completeness: { specimens_total: number; with_contact_angle: number; with_corrosion: number; with_both: number; with_exposed_area: number };
  recent_experiments: { id: number; code: string; status: string; type: string; is_demo: boolean; created_at: string }[];
  activity: { id: number; entity_type: string; action: string; summary: string; created_at: string }[];
};
type Summary = { targets: Record<string, { records: number; groups: number; with_contact_angle: number; excluded: number }>; policy: { min_groups_exploratory: number; min_groups_validated: number } };

const ACTIVITY_ICON: Record<string, typeof Droplets> = { contact_angle_run: Droplets, corrosion_run: Zap, ml_comparison: BrainCircuit, specimen: Database, experiment: Database, demo: Settings2, settings: Settings2 };

function Bar({ label, n, total }: { label: string; n: number; total: number }) {
  const pct = total ? Math.round((100 * n) / total) : 0;
  return (
    <div>
      <div className="flex justify-between gap-3 text-xs"><span className="text-ink-2">{label}</span><span className="num shrink-0 text-muted">{n}/{total}</span></div>
      <div className="mt-1.5 h-1.5 rounded-full bg-panel-2" role="progressbar" aria-label={label} aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** Progress of independent specimen groups towards the configured readiness thresholds. */
function ReadinessTrack({ groups, explore, validated }: { groups: number; explore: number; validated: number }) {
  const max = Math.max(validated, groups) * 1.08;
  const at = (v: number) => `${(100 * v) / max}%`;
  const level = groups >= validated ? "adequate" : groups >= explore ? "exploratory" : "insufficient";
  return (
    <div>
      <div className="relative h-2.5 rounded-full bg-panel-2" role="progressbar" aria-label="Independent specimen groups with a valid i_corr" aria-valuenow={groups} aria-valuemin={0} aria-valuemax={validated}>
        <div className={cx("absolute inset-y-0 left-0 rounded-full", level === "adequate" ? "bg-good" : level === "exploratory" ? "bg-warn" : "bg-bad/70")} style={{ width: at(groups) }} />
        {[explore, validated].map((v) => <div key={v} className="absolute -top-1 h-4.5 w-px bg-ink-2/70" style={{ left: at(v) }} aria-hidden />)}
      </div>
      <div className="relative mt-1.5 h-4 text-[10.5px] text-muted">
        <span className="absolute -translate-x-1/2 whitespace-nowrap" style={{ left: at(explore) }}>{explore} · exploratory</span>
        <span className="absolute -translate-x-full whitespace-nowrap" style={{ left: at(validated) }}>{validated} · validated</span>
      </div>
    </div>
  );
}

function nextStep(d: Dash, groups: number, explore: number): { text: string; href: string; cta: string; icon: ReactNode } {
  const c = d.completeness;
  if (!c.specimens_total) return { text: "Register the physical specimens you will test.", href: "/experiments?new=specimen", cta: "Register specimen", icon: <Plus className="size-4" /> };
  if (c.with_contact_angle < c.specimens_total) return { text: `${c.specimens_total - c.with_contact_angle} specimen(s) have no accepted contact angle yet.`, href: "/wettability", cta: "Capture contact angle", icon: <Camera className="size-4" /> };
  if (c.with_corrosion < c.specimens_total) return { text: `${c.specimens_total - c.with_corrosion} specimen(s) have no electrochemical run yet.`, href: "/corrosion", cta: "Import corrosion data", icon: <FileUp className="size-4" /> };
  if (groups < explore) return { text: `${explore - groups} more specimen(s) with a confirmed i_corr are needed before a grouped comparison can run.`, href: "/corrosion", cta: "Import corrosion data", icon: <FileUp className="size-4" /> };
  return { text: "The dataset supports a grouped baseline vs contact-angle comparison.", href: "/ml-studio", cta: "Open ML Studio", icon: <BrainCircuit className="size-4" /> };
}

export default function Dashboard() {
  const { data: d, error, loading } = useApi<Dash>("/api/dashboard");
  const sum = useApi<Summary>("/api/ml/dataset-summary?data_source=real");
  const actions = (
    <>
      <Link href="/wettability"><Button variant="primary" icon={<Camera className="size-4" />}>Capture contact angle</Button></Link>
      <Link href="/corrosion"><Button icon={<FileUp className="size-4" />}>Import corrosion data</Button></Link>
      <Link href="/showcase"><Button variant="ghost" icon={<Presentation className="size-4" />}>Showcase example</Button></Link>
    </>
  );
  const ic = sum.data?.targets.i_corr;
  const explore = sum.data?.policy.min_groups_exploratory ?? 4;
  const validated = sum.data?.policy.min_groups_validated ?? 15;
  return (
    <>
      <PageHeader eyebrow="WETCOR AI · Overview" title="Laboratory overview"
        subtitle="Quantitative surface wettability, electrochemical corrosion characterisation and ML-assisted corrosion prediction — every figure below is computed from the local database." actions={actions} />
      {error ? <Alert tone="bad" title="Backend not reachable">{error}</Alert> : loading || !d ? <Spinner /> : (
        <div className="flex flex-col gap-5">
          <section className="grid overflow-hidden rounded-lg border border-line bg-panel lg:grid-cols-[1.35fr_1fr]" aria-labelledby="rq">
            <div className="relative p-6">
              <div className="absolute inset-y-0 left-0 w-0.5 bg-accent" aria-hidden />
              <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted">Research question</div>
              <h2 id="rq" className="mt-2 max-w-2xl text-lg font-medium leading-snug text-ink">
                Does the water contact angle add predictive information about electrochemical corrosion beyond material and test conditions?
              </h2>
              <div className="mt-5 max-w-xl">
                <div className="mb-2 flex items-baseline justify-between text-xs">
                  <span className="text-ink-2">Independent specimens with a confirmed i<sub>corr</sub></span>
                  <span className="num text-sm font-semibold text-ink">{ic?.groups ?? "—"}</span>
                </div>
                <ReadinessTrack groups={ic?.groups ?? 0} explore={explore} validated={validated} />
                <p className="mt-3 text-xs text-muted">
                  {ic ? `${ic.records} run(s) with a valid target, ${ic.with_contact_angle} linked to a contact angle${ic.excluded ? `, ${ic.excluded} excluded (unreliable or unconfirmed fits)` : ""}.` : "Loading dataset summary…"} Thresholds are the configurable readiness policy, not a universal sample-size rule.
                </p>
              </div>
            </div>
            {(() => {
              const s = nextStep(d, ic?.groups ?? 0, explore);
              return (
                <div className="flex flex-col justify-between gap-4 border-t border-line bg-panel-2/40 p-6 lg:border-l lg:border-t-0">
                  <div>
                    <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted">Next step</div>
                    <p className="mt-2 text-sm text-ink-2">{s.text}</p>
                  </div>
                  <Link href={s.href} className="self-start"><Button variant="secondary" icon={s.icon}>{s.cta} <ArrowRight className="size-3.5" /></Button></Link>
                </div>
              );
            })()}
          </section>

          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Specimens" value={d.real.specimens} />
            <Stat label="Contact-angle runs" value={d.real.contact_angle_runs} />
            <Stat label="Electrochemical runs" value={d.real.corrosion_runs} />
            <Stat label="Experiments" value={d.real.experiments} />
            <Stat label="Completed" value={d.real.completed_experiments} sub="experiments marked complete" />
            <Stat label="ML-eligible records" value={d.real.ml_eligible_records} tone="accent" sub="valid target + contact angle" />
          </div>

          {d.demo.specimens > 0 && (
            <div className="demo-stripe flex flex-wrap items-center gap-3 rounded-md border border-warn/50 px-4 py-2 text-sm text-warn">
              <DemoBadge /> Demo workspace loaded: {d.demo.specimens} specimens, {d.demo.contact_angle_runs} contact-angle runs, {d.demo.corrosion_runs} electrochemical runs — excluded from every figure above.
              <Link className="ml-auto underline underline-offset-2" href="/settings">Manage</Link>
            </div>
          )}

          {d.real.specimens === 0 && d.recent_experiments.length === 0 ? (
            <Card>
              <EmptyState title="No laboratory data yet" action={<div className="flex flex-wrap justify-center gap-2"><Link href="/experiments?new=specimen"><Button variant="primary" icon={<Plus className="size-4" />}>Register first specimen</Button></Link><Link href="/settings"><Button variant="ghost">Load demo workspace</Button></Link></div>}>
                Register a specimen, measure its contact angle in the Wettability Lab and import its potentiostat file in the Corrosion Lab.
              </EmptyState>
            </Card>
          ) : (
            <div className="grid gap-5 lg:grid-cols-3">
              <Card title="Data completeness">
                {d.completeness.specimens_total === 0 ? <p className="text-sm text-muted">No real specimens registered yet.</p> : (
                  <div className="flex flex-col gap-3.5">
                    <Bar label="Accepted contact angle" n={d.completeness.with_contact_angle} total={d.completeness.specimens_total} />
                    <Bar label="Electrochemical data" n={d.completeness.with_corrosion} total={d.completeness.specimens_total} />
                    <Bar label="Both measurements" n={d.completeness.with_both} total={d.completeness.specimens_total} />
                    <Bar label="Exposed area recorded" n={d.completeness.with_exposed_area} total={d.completeness.specimens_total} />
                  </div>
                )}
                <p className="mt-4 border-t border-line pt-3 text-xs text-muted">{d.ml_runs} ML comparison(s) recorded · <Link className="text-accent hover:underline" href="/ml-studio">ML Studio</Link></p>
              </Card>
              <Card title="Recent experiments" actions={<Link className="text-xs text-accent hover:underline" href="/experiments?tab=experiments">All</Link>}>
                {d.recent_experiments.length === 0 ? <div className="text-sm text-muted">No experiments yet.</div> : (
                  <ul className="-my-1 divide-y divide-line text-sm">
                    {d.recent_experiments.map((e) => (
                      <li key={e.id} className="flex items-center gap-2 py-2">
                        <Link className="whitespace-nowrap font-medium text-accent hover:underline" href={`/experiments/${e.id}`}>{e.code}</Link>
                        {e.is_demo && <DemoBadge compact />}
                        <span className="flex-1 truncate text-xs text-muted">{e.type}</span>
                        <Badge tone={e.status === "complete" ? "good" : e.status === "invalid" ? "bad" : "neutral"}>{e.status.replace("_", " ")}</Badge>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title="Recent activity">
                <ol className="-my-1 divide-y divide-line">
                  {d.activity.slice(0, 7).map((a) => {
                    const Icon = ACTIVITY_ICON[a.entity_type] ?? Database;
                    return (
                      <li key={a.id} className="flex gap-2.5 py-2">
                        <Icon className="mt-0.5 size-3.5 shrink-0 text-muted" aria-hidden />
                        <div className="min-w-0">
                          <div className="line-clamp-2 text-[13px] text-ink-2" title={a.summary}>{a.summary}</div>
                          <div className="text-[11px] text-muted">{fmtDate(a.created_at)}</div>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </Card>
            </div>
          )}
        </div>
      )}
    </>
  );
}
