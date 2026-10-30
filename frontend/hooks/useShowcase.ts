"use client";

import { useEffect, useState } from "react";
import { useApi } from "@/hooks/useApi";
import type { RunData as CorrosionPlotsRun } from "@/components/CorrosionPlots";
import { apiUrl, type CARun, type CorrosionRun, type Experiment, type Metric, type Specimen } from "@/lib/api";
import { SNAPSHOT_URL, isStaticDemo } from "@/lib/mode";

export type Manifest = {
  title: string; summary: string;
  contact_angle: { source: { title: string; author: string; url: string; licence: string; licence_url: string; substrate: string }; preprocessing: string[];
    correction_reason: string; reference: { source: string; left_deg: number; right_deg: number } };
};
export type ShowcaseIds = { specimen_id: number; experiment_id: number; contact_angle_run_ids: number[]; corrosion_runs: { id: number; method: string }[] };
export type Status = { loaded: boolean; manifest: Manifest; showcase: ShowcaseIds | null };
export type SpecDetail = { specimen: Specimen; experiments: Experiment[]; artifacts: { id: number; kind: string; original_filename: string; sha256: string }[] };
export type RunDetail = CorrosionRun & { metrics: Metric[]; current_analysis: { fit?: Record<string, unknown>; notes: string[]; warnings: string[] } | null; raw_file: { sha256: string; original_filename: string } };
type Snapshot = { manifest: Manifest; showcase: ShowcaseIds; spec: SpecDetail; ca: CARun; pdp: RunDetail; pdpData: CorrosionPlotsRun; ocp: RunDetail; ocpData: CorrosionPlotsRun;
  images: { source: string; overlay: string }; report: string };

export type Q<T> = { data: T | null; loading: boolean; error: string | null; reload: () => void };

/** One source for the showcase page: the live API, or the bundled snapshot in static-demo mode. */
export function useShowcase() {
  const staticMode = isStaticDemo();
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [snapErr, setSnapErr] = useState<string | null>(null);
  useEffect(() => {
    if (!staticMode) return;
    fetch(SNAPSHOT_URL).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`snapshot HTTP ${r.status}`)))).then(setSnap).catch((e: Error) => setSnapErr(e.message));
  }, [staticMode]);

  const live = useApi<Status>(staticMode ? null : "/api/demo/showcase");
  const sc = live.data?.showcase;
  const caId = sc?.contact_angle_run_ids[0];
  const pdpId = sc?.corrosion_runs.find((r) => r.method === "pdp")?.id;
  const ocpId = sc?.corrosion_runs.find((r) => r.method === "ocp")?.id;
  const lSpec = useApi<SpecDetail>(sc ? `/api/specimens/${sc.specimen_id}` : null);
  const lCa = useApi<CARun>(caId ? `/api/wettability/measurements/${caId}` : null);
  const lPdp = useApi<RunDetail>(pdpId ? `/api/corrosion/runs/${pdpId}` : null);
  const lPdpData = useApi<CorrosionPlotsRun>(pdpId ? `/api/corrosion/runs/${pdpId}/data` : null);
  const lOcp = useApi<RunDetail>(ocpId ? `/api/corrosion/runs/${ocpId}` : null);
  const lOcpData = useApi<CorrosionPlotsRun>(ocpId ? `/api/corrosion/runs/${ocpId}/data` : null);

  const fixed = <T,>(data: T | undefined): Q<T> => ({ data: data ?? null, loading: !data && !snapErr, error: null, reload: () => undefined });
  if (staticMode) {
    const status: Q<Status> = snap
      ? { data: { loaded: true, manifest: snap.manifest, showcase: snap.showcase }, loading: false, error: null, reload: () => undefined }
      : { data: null, loading: !snapErr, error: snapErr, reload: () => undefined };
    return { staticMode, status, spec: fixed(snap?.spec), ca: fixed(snap?.ca), pdp: fixed(snap?.pdp), pdpData: fixed(snap?.pdpData), ocp: fixed(snap?.ocp), ocpData: fixed(snap?.ocpData),
      sourceImg: snap?.images.source ?? null, overlayImg: snap?.images.overlay ?? null, reportUrl: snap?.report ?? null, ids: { caId, pdpId, ocpId } };
  }
  const sourceArt = lSpec.data?.artifacts.find((a) => a.kind === "source_image");
  return {
    staticMode, status: live as Q<Status>, spec: lSpec as Q<SpecDetail>, ca: lCa as Q<CARun>, pdp: lPdp as Q<RunDetail>, pdpData: lPdpData as Q<CorrosionPlotsRun>,
    ocp: lOcp as Q<RunDetail>, ocpData: lOcpData as Q<CorrosionPlotsRun>,
    sourceImg: sourceArt ? apiUrl(`/api/artifacts/${sourceArt.id}/download?inline=true`) : null,
    overlayImg: lCa.data?.overlay_artifact_id ? apiUrl(`/api/artifacts/${lCa.data.overlay_artifact_id}/download?inline=true`) : null,
    reportUrl: sc ? apiUrl(`/api/reports/experiment/${sc.experiment_id}`) : null, ids: { caId, pdpId, ocpId },
  };
}
