"use client";

import { ExternalLink, FileText, Presentation } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { CorrosionPlots, type RunData } from "@/components/CorrosionPlots";
import { Alert, Badge, Button, Card, DemoBanner, EmptyState, KV, OriginBadge, PageHeader, Spinner, StatusDot, Table } from "@/components/ui";
import { api, type Diagnostic, type Metric } from "@/lib/api";
import { REPO_URL } from "@/lib/mode";
import { fmtDeg, fmtNum, unit } from "@/lib/format";
import { useShowcase } from "@/hooks/useShowcase";
import { CA_NOTE, classTone } from "@/lib/wettability";

function Section({ n, title, origin, children }: { n: number; title: string; origin?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-t border-line pt-8 xl:grid-cols-[180px_minmax(0,1fr)]" aria-labelledby={`s${n}`}>
      <div>
        <div className="font-mono text-3xl font-semibold text-accent/80">{String(n).padStart(2, "0")}</div>
        <h2 id={`s${n}`} className="mt-1 text-base font-semibold text-ink">{title}</h2>
        {origin && <div className="mt-2 flex flex-wrap gap-1.5">{origin}</div>}
      </div>
      <div className="flex min-w-0 flex-col gap-4">{children}</div>
    </section>
  );
}

function MetricTable({ metrics, names }: { metrics: Metric[]; names: string[] }) {
  const rows = names.map((n) => metrics.find((m) => m.name === n)).filter(Boolean) as Metric[];
  return (
    <Table head={["Quantity", "Value", "Origin", "Method", "Status"]}>
      {rows.map((m) => (
        <tr key={m.name}>
          <td className="whitespace-normal! text-ink">{m.label}</td>
          <td className="num font-semibold">{fmtNum(m.value)} <span className="font-normal text-ink-2">{unit(m.unit)}</span></td>
          <td><OriginBadge origin={m.origin} /></td>
          <td className="min-w-48 whitespace-normal! font-mono text-[11px] text-ink-2">{m.formula}</td>
          <td>{m.valid ? <Badge tone="good">valid</Badge> : <Badge tone="bad">unreliable</Badge>}</td>
        </tr>
      ))}
    </Table>
  );
}

export default function ShowcasePage() {
  const { staticMode, status: st, spec, ca, pdp, pdpData, ocp, ocpData, sourceImg, overlayImg, reportUrl, ids } = useShowcase();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const sc = st.data?.showcase;
  const { caId, pdpId } = ids;

  const load = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api("/api/demo/showcase/load", { method: "POST" });
      st.reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (st.loading && !st.data) return <Spinner />;
  if (st.error || !st.data) return <Alert tone="bad" title="Showcase unavailable">{st.error}</Alert>;
  const m = st.data.manifest;
  const header = (
    <PageHeader eyebrow="Showcase · Pre-computed test" title={m.title} subtitle={m.summary}
      actions={sc && <>
        {!staticMode && <Link href={`/experiments/${sc.experiment_id}`}><Button icon={<ExternalLink className="size-4" />}>Experiment record</Button></Link>}
        {reportUrl && <a href={reportUrl} target="_blank" rel="noreferrer"><Button variant="primary" icon={<FileText className="size-4" />}>Printable report</Button></a>}
      </>} />
  );

  if (!st.data.loaded || !sc) {
    return (
      <>
        {header}
        <Card>
          <EmptyState icon={<Presentation className="size-9" />} title="Showcase example not loaded"
            action={<Button variant="primary" size="lg" busy={busy} onClick={load}>Load showcase example</Button>}>
            Creates one complete, already-analysed test you can open during a presentation: specimen and conditions, a real goniometer frame analysed by WETCOR AI with
            the instrument&apos;s own reading for comparison, and synthetic OCP and polarisation runs with Tafel analysis. It is kept separate from your laboratory records
            (flagged as demo) and is removed by Settings → Reset demo workspace.
          </EmptyState>
          {err && <div className="mt-3"><Alert tone="bad">{err}</Alert></div>}
        </Card>
      </>
    );
  }

  const s = spec.data?.specimen;
  const exp = spec.data?.experiments[0];
  const ref = m.contact_angle.reference;
  const refMean = (ref.left_deg + ref.right_deg) / 2;
  const r = ca.data;
  const diags = ((r?.diagnostics?.diagnostics ?? []) as Diagnostic[]).filter((d) => ["contrast", "baseline", "contour_points", "poly_rms_left", "circle_rel_rms", "lr_diff", "method_agreement"].includes(d.key));
  const autoErr = (r?.auto_result as { errors?: string[] } | null)?.errors?.[0];

  return (
    <>
      {header}
      <DemoBanner>Contact angle measured by WETCOR AI on a public goniometer frame used as a stand-in for a steel plate; the electrochemical runs are synthetic. Not evidence about any real material.</DemoBanner>
      <div className="flex flex-col gap-8 pb-10">
        <Section n={1} title="Specimen and test inputs" origin={<Badge>recorded inputs</Badge>}>
          {!s || !exp ? <Spinner /> : (
            <div className="grid gap-4 md:grid-cols-2">
              <Card title={`Specimen ${s.code}`}>
                <KV items={[["Material", s.material], ["Surface preparation", s.surface_preparation], ["Dimensions", s.dimensions],
                  ["Exposed area", `${s.exposed_area_cm2} cm²`], ["Roughness Ra", s.roughness_ra_um != null ? `${s.roughness_ra_um} µm` : null]]} />
              </Card>
              <Card title={`Experiment ${exp.code}`}>
                <KV items={[["Electrolyte", `${exp.electrolyte} ${exp.concentration_value} ${exp.concentration_unit}`], ["Temperature", `${exp.temperature_c} °C`],
                  ["Reference electrode", exp.reference_electrode], ["Procedure", exp.procedure]]} />
              </Card>
            </div>
          )}
        </Section>

        <Section n={2} title="Contact angle from the droplet image" origin={<><OriginBadge origin="measured" /><Badge>public stand-in image</Badge></>}>
          {!r ? <Spinner /> : (
            <>
              <div className="grid gap-4 md:grid-cols-2">
                <figure className="rounded-lg border border-line bg-panel p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {sourceImg && <img src={sourceImg} alt="Original goniometer screenshot from Wikimedia Commons" className="w-full rounded" />}
                  <figcaption className="mt-2 text-xs text-muted">
                    Input · source frame: “{m.contact_angle.source.title}” by {m.contact_angle.source.author},{" "}
                    <a className="text-accent underline" href={m.contact_angle.source.url} target="_blank" rel="noreferrer">Wikimedia Commons</a>,{" "}
                    <a className="text-accent underline" href={m.contact_angle.source.licence_url} target="_blank" rel="noreferrer">{m.contact_angle.source.licence}</a>. Substrate {m.contact_angle.source.substrate}.
                  </figcaption>
                </figure>
                <figure className="rounded-lg border border-line bg-panel p-3">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {overlayImg && <img src={overlayImg} alt="WETCOR AI annotated analysis of the droplet" className="w-full rounded" />}
                  <figcaption className="mt-2 text-xs text-muted">Output · WETCOR AI analysis: cyan baseline, green detected boundary, amber contact points and tangents, magenta circle fit.</figcaption>
                </figure>
              </div>
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
                <Card title="Result">
                  <div className="flex items-end justify-between gap-3">
                    <div>
                      <div className="text-xs text-muted">Mean water contact angle</div>
                      <div className="num text-5xl font-semibold text-ink">{fmtDeg(r.mean_deg)}</div>
                    </div>
                    {r.classification && <Badge tone={classTone(r.classification)} className="text-xs">{r.classification}</Badge>}
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-2 text-center">
                    <div className="rounded-md border border-line bg-panel-2 py-2"><div className="text-[11px] text-muted">Left θL</div><div className="num text-lg font-semibold">{fmtDeg(r.left_deg)}</div></div>
                    <div className="rounded-md border border-line bg-panel-2 py-2"><div className="text-[11px] text-muted">Right θR</div><div className="num text-lg font-semibold">{fmtDeg(r.right_deg)}</div></div>
                  </div>
                  <div className="mt-4 text-sm text-ink-2">Method <code>{r.method}</code> · algorithm {r.algorithm_version}</div>
                  <p className="mt-2 text-xs text-muted">{m.contact_angle.correction_reason}{autoErr && <> Automatic attempt: “{autoErr}”</>}</p>
                </Card>
                <Card title="Comparison with the instrument's own reading">
                  <Table head={["", "Left", "Right", "Mean"]}>
                    <tr><td className="text-ink">WETCOR AI (local tangent)</td><td className="num">{fmtDeg(r.left_deg)}</td><td className="num">{fmtDeg(r.right_deg)}</td><td className="num font-semibold">{fmtDeg(r.mean_deg)}</td></tr>
                    <tr><td className="text-ink">Instrument software (Young–Laplace)</td><td className="num">{fmtDeg(ref.left_deg)}</td><td className="num">{fmtDeg(ref.right_deg)}</td><td className="num font-semibold">{fmtDeg(refMean)}</td></tr>
                    <tr><td className="text-ink-2">Difference</td><td className="num">{fmtDeg((r.left_deg ?? 0) - ref.left_deg)}</td><td className="num">{fmtDeg((r.right_deg ?? 0) - ref.right_deg)}</td><td className="num">{fmtDeg((r.mean_deg ?? 0) - refMean)}</td></tr>
                  </Table>
                  <p className="mt-3 text-xs text-muted">
                    Both agree on the classification. The few-degree offset is expected here: the droplet is only ~150 px wide (≈1.5° per pixel of baseline height), the
                    instrument fits a Young–Laplace profile while WETCOR fits local tangents, and the reference value is a third-party reading. This is one image, not a calibration.
                  </p>
                </Card>
              </div>
              <Card title="Quality diagnostics">
                <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
                  {diags.map((d) => <li key={d.key} className="flex items-center gap-2"><StatusDot status={d.status} /><span className="flex-1 text-ink-2">{d.label}</span><span className="num">{String(d.value)} {d.unit}</span></li>)}
                </ul>
                <details className="mt-3 text-xs text-muted"><summary className="cursor-pointer">Image preprocessing (documented)</summary>
                  <ul className="mt-1 list-disc pl-5">{m.contact_angle.preprocessing.map((p) => <li key={p}>{p}</li>)}</ul></details>
                <p className="mt-3 border-t border-line pt-2 text-xs text-muted">{CA_NOTE}</p>
              </Card>
            </>
          )}
        </Section>

        <Section n={3} title="Open-circuit potential" origin={<><OriginBadge origin="calculated" /><Badge tone="warn">synthetic data</Badge></>}>
          {!ocp.data || !ocpData.data ? <Spinner /> : (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <Card title="E vs time" pad><CorrosionPlots run={ocpData.data} fit={ocp.data.current_analysis?.fit} demo /></Card>
              <Card title="Stability">
                <MetricTable metrics={ocp.data.metrics} names={["ocp_mean", "ocp_std", "ocp_drift", "ocp_duration"]} />
                <p className="mt-3 text-xs text-muted">OCP shows when the surface has stabilised. It is never converted into a corrosion rate.</p>
              </Card>
            </div>
          )}
        </Section>

        <Section n={4} title="Polarisation and Tafel analysis" origin={<><OriginBadge origin="calculated" /><Badge tone="warn">synthetic data</Badge></>}>
          {!pdp.data || !pdpData.data ? <Spinner /> : (
            <>
              <Card title="E vs log|i| with fitted Tafel lines"><CorrosionPlots run={pdpData.data} fit={pdp.data.current_analysis?.fit} demo /></Card>
              <Card title="Results">
                <MetricTable metrics={pdp.data.metrics} names={["e_corr_tafel", "i_corr", "beta_a", "beta_c", "stern_geary_B", "corrosion_rate"]} />
                <p className="mt-3 text-xs text-muted">
                  Tafel regions 70–220 mV from E<sub>corr</sub> on both branches (user-confirmed). Corrosion rate uses the Fe → Fe²⁺ reference profile (EW 27.92 g/eq, ρ 7.874 g/cm³)
                  with its source recorded. Source file SHA-256 {pdp.data.raw_file.sha256.slice(0, 16)}…
                </p>
              </Card>
            </>
          )}
        </Section>

        <Section n={5} title="What this example shows" origin={<Badge>summary</Badge>}>
          <Card>
            <ul className="list-disc space-y-2 pl-5 text-sm text-ink-2">
              <li>Every value on this page was computed by WETCOR AI from the stored files and recorded inputs; nothing was typed in as a result.</li>
              <li>The surface is <strong className="text-ink">{r?.classification ?? "—"}</strong> ({fmtDeg(r?.mean_deg)}). Wettability alone does not establish corrosion resistance.</li>
              <li>The corrosion current density and rate come from a documented Tafel procedure with recorded regions, area and material properties.</li>
              <li>One specimen cannot answer the research question: the ML comparison needs at least 4 (exploratory) and ideally 15 independent specimens with both measurements.</li>
            </ul>
            {staticMode ? (
              <p className="mt-4 border-t border-line pt-3 text-xs text-muted">
                This hosted page is a static snapshot of a test computed by WETCOR AI. The full application — live camera capture, import of your own potentiostat files,
                the experiment database and ML Studio — runs locally: <a className="text-accent underline" href={REPO_URL} target="_blank" rel="noreferrer">source and setup on GitHub</a>.
              </p>
            ) : (
              <div className="mt-4 flex flex-wrap gap-2">
                {caId && <Link href={`/wettability/${caId}`}><Button size="sm">Contact-angle record</Button></Link>}
                {pdpId && <Link href={`/corrosion/runs/${pdpId}`}><Button size="sm">Polarisation run</Button></Link>}
                <Link href={`/experiments/specimens/${sc.specimen_id}`}><Button size="sm">Specimen</Button></Link>
              </div>
            )}
          </Card>
        </Section>
      </div>
    </>
  );
}
