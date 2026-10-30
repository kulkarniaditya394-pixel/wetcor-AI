"use client";

import { Save } from "lucide-react";
import { useEffect, useState } from "react";
import { useBackendHealth } from "@/components/Sidebar";
import { Alert, Badge, Button, Card, DemoBadge, Input, KV, PageHeader, Select, Spinner } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { API_URL, api } from "@/lib/api";

type SettingsResp = { analysis: Record<string, Record<string, number | string>>; spec: Record<string, Record<string, { default: number | string; description: string }>>; data_dir: string };
const SECTION = { wettability: "Contact-angle quality limits", electrochemistry: "Electrochemistry limits", ml: "ML readiness policy" };

export default function SettingsPage() {
  const health = useBackendHealth(10000);
  const version = useApi<Record<string, string>>("/api/version");
  const s = useApi<SettingsResp>("/api/settings");
  const demo = useApi<{ specimens: number; contact_angle_runs: number; corrosion_runs: number; workspace_loaded: boolean }>("/api/demo");
  const [vals, setVals] = useState<Record<string, Record<string, string>>>({});
  const [msg, setMsg] = useState<{ tone: "good" | "bad"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");

  useEffect(() => {
    if (s.data) setVals(Object.fromEntries(Object.entries(s.data.analysis).map(([k, v]) => [k, Object.fromEntries(Object.entries(v).map(([a, b]) => [a, String(b)]))])));
  }, [s.data]);

  const save = async () => {
    setBusy("save");
    try {
      const analysis = Object.fromEntries(Object.entries(vals).map(([sec, items]) => [sec, Object.fromEntries(Object.entries(items).map(([k, v]) =>
        [k, typeof s.data!.spec[sec][k].default === "string" ? v : Number(v)]))]));
      await api("/api/settings", { method: "PUT", json: { analysis } });
      setMsg({ tone: "good", text: "Limits saved. New analyses record the limits in force when they ran." });
      s.reload();
    } catch (e) {
      setMsg({ tone: "bad", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <PageHeader eyebrow="System" title="Settings" subtitle="Local service status, analysis limits and the synthetic demo workspace." />
      {msg && <div className="mb-4"><Alert tone={msg.tone}>{msg.text}</Alert></div>}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)]">
        <div className="flex flex-col gap-5">
          <Card title="Local services">
            <KV items={[
              ["Backend", <Badge key="b" tone={health === "online" ? "good" : health === "checking" ? "neutral" : "bad"}>{health}</Badge>],
              ["API URL", <code key="u">{API_URL}</code>],
              ["Version", version.data ? `${version.data.name} ${version.data.version}` : null],
              ["Contact-angle algorithm", version.data?.contact_angle_algorithm],
              ["Electrochemistry methods", version.data?.electrochemistry_methods],
              ["Data directory", s.data?.data_dir],
            ]} />
            <p className="mt-3 text-xs text-muted">The backend listens on the loopback interface only. Images, instrument files and models stay on this computer; no cloud service is contacted.</p>
          </Card>
          <Card title="Demo workspace" actions={<DemoBadge />}>
            {!demo.data ? <Spinner /> : (
              <div className="flex flex-col gap-3 text-sm">
                <p className="text-ink-2">Loads 10 synthetic specimens with generated droplet images, OCP/LPR/polarisation/EIS files and analyses so every screen can be exercised before laboratory data exist.
                  Synthetic corrosion parameters are drawn independently of the synthetic contact angles: the demo cannot show a real relationship. Demo records are excluded from real counts, datasets and reports unless explicitly included.</p>
                <p className="text-ink-2">A single pre-computed presentation example is available on the <a className="text-accent underline" href="/showcase">Showcase</a> page; reset also removes it.</p>
                <div>Currently loaded: <strong>{demo.data.specimens}</strong> specimens, {demo.data.contact_angle_runs} contact-angle runs, {demo.data.corrosion_runs} electrochemical runs.</div>
                {!demo.data.workspace_loaded && (
                  <Button variant="secondary" busy={busy === "load"} onClick={async () => {
                    setBusy("load");
                    try { await api("/api/demo/load", { method: "POST" }); setMsg({ tone: "good", text: "Demo workspace loaded (DEMO — SYNTHETIC DATA)." }); demo.reload(); }
                    catch (e) { setMsg({ tone: "bad", text: (e as Error).message }); } finally { setBusy(null); }
                  }}>Load demo data</Button>
                )}
                {demo.data.specimens > 0 && (
                  <div className="flex flex-col gap-2 rounded-md border border-warn/40 p-3">
                    <label htmlFor="reset" className="text-xs text-muted">Reset removes only records flagged as demo. Type <code>RESET-DEMO</code>.</label>
                    <div className="flex gap-2">
                      <Input id="reset" className="w-40" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
                      <Button variant="danger" disabled={confirm !== "RESET-DEMO"} busy={busy === "reset"} onClick={async () => {
                        setBusy("reset");
                        try { await api("/api/demo?confirm=RESET-DEMO", { method: "DELETE" }); setConfirm(""); setMsg({ tone: "good", text: "Demo workspace removed." }); demo.reload(); }
                        catch (e) { setMsg({ tone: "bad", text: (e as Error).message }); } finally { setBusy(null); }
                      }}>Reset demo workspace</Button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
        <Card title="Analysis limits" actions={<Button size="sm" variant="primary" icon={<Save className="size-3.5" />} busy={busy === "save"} onClick={save}>Save</Button>}>
          {!s.data ? <Spinner /> : (
            <div className="flex flex-col gap-5">
              <Alert tone="info">These are software quality-control settings, not physical constants. Each saved result records the limits used to compute it.</Alert>
              {Object.entries(s.data.spec).map(([sec, items]) => (
                <section key={sec}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{SECTION[sec as keyof typeof SECTION] ?? sec}</h3>
                  <div className="flex flex-col divide-y divide-line rounded-md border border-line">
                    {Object.entries(items).map(([k, meta]) => (
                      <div key={k} className="grid items-center gap-2 px-3 py-2 sm:grid-cols-[minmax(0,1fr)_140px]">
                        <label htmlFor={`${sec}-${k}`} className="min-w-0 break-words text-sm"><code className="text-ink">{k}</code><span className="block text-xs text-muted">{meta.description} (default {String(meta.default)})</span></label>
                        {k === "primary_method" ? (
                          <Select id={`${sec}-${k}`} value={vals[sec]?.[k] ?? ""} onChange={(e) => setVals({ ...vals, [sec]: { ...vals[sec], [k]: e.target.value } })}>
                            <option value="polynomial">polynomial</option><option value="circle">circle</option>
                          </Select>
                        ) : (
                          <Input id={`${sec}-${k}`} value={vals[sec]?.[k] ?? ""} type={typeof meta.default === "string" ? "text" : "number"} step="any"
                            onChange={(e) => setVals({ ...vals, [sec]: { ...vals[sec], [k]: e.target.value } })} />
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
