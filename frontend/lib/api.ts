import { isStaticDemo } from "./mode";

/** Client for the local FastAPI backend (or, on the hosted static site, the in-browser engine). Nothing is sent anywhere else. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8100").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function detailText(detail: unknown): string {
  if (!detail) return "Request failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail
      .map((d) => (typeof d === "object" && d ? `${(d as { loc?: unknown[] }).loc?.slice(-1)[0] ?? ""}: ${(d as { msg?: string }).msg ?? ""}` : String(d)))
      .join("; ");
  return JSON.stringify(detail);
}

type Init = Omit<RequestInit, "body"> & { json?: unknown; body?: BodyInit };

export async function api<T = unknown>(path: string, init: Init = {}): Promise<T> {
  if (isStaticDemo()) {
    // Hosted static site: no backend; the analysis runs in the browser (lib/engine.ts).
    const { engineRoute } = await import("./engine");
    return (await engineRoute(path, init)).value as T;
  }
  const { json, headers, ...rest } = init;
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      ...rest,
      headers: json !== undefined ? { "Content-Type": "application/json", ...headers } : headers,
      body: json !== undefined ? JSON.stringify(json) : init.body,
    });
  } catch {
    throw new ApiError(0, `Cannot reach the local backend at ${API_URL}. Is run-local.ps1 running?`);
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detailText(detail));
  }
  const type = res.headers.get("content-type") || "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const apiUrl = (path: string) => API_URL + path;

export function form(fields: Record<string, string | Blob | [Blob, string]>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) {
    if (Array.isArray(v)) fd.append(k, v[0], v[1]);
    else fd.append(k, v);
  }
  return fd;
}

// ---------- domain types (subset of the API schemas) ----------
export type Specimen = {
  id: number; code: string; material: string; batch_source: string | null; dimensions: string | null; surface_preparation: string | null;
  roughness_ra_um: number | null; exposed_area_cm2: number | null; notes: string | null; is_demo: boolean; created_at: string; updated_at: string;
  n_experiments?: number; n_contact_angle?: number; n_corrosion?: number;
};
export type Experiment = {
  id: number; code: string; specimen_id: number; specimen_code?: string; experiment_type: string; performed_at: string | null; operator: string | null;
  electrolyte: string | null; concentration_value: number | null; concentration_unit: string | null; temperature_c: number | null;
  instrument: string | null; reference_electrode: string | null; procedure: string | null; notes: string | null; status: string; is_demo: boolean;
  created_at: string; n_contact_angle?: number; n_corrosion?: number;
};
export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
export type Diagnostic = { key: string; label: string; value: unknown; unit: string; status: "pass" | "warn" | "fail"; note: string };
export type Pt = [number, number];
export type CAGeometry = {
  roi?: [number, number, number, number]; baseline?: Pt[]; baseline_points?: Pt[]; contact_left?: Pt; contact_right?: Pt;
  tangent_left?: Pt[]; tangent_right?: Pt[]; apex?: Pt; contour?: Pt[]; circle?: { centre: Pt; radius: number }; tilt_deg?: number;
  fit_radius_px?: number; droplet_height_px?: number; contact_width_px?: number;
};
export type Classification = { label: "hydrophilic" | "hydrophobic" | "boundary"; text: string; uncertain: boolean; reasons: string[]; recommend_repeat: boolean };
export type CAResult = {
  status: "ok" | "needs_correction" | "failed"; method: string | null; fit_method?: string; algorithm_version: string;
  left_deg: number | null; right_deg: number | null; mean_deg: number | null; lr_diff_deg: number | null; classification: Classification | null;
  methods: Record<string, { status: string; angle_deg?: number; mean_deg?: number; left_deg?: number; right_deg?: number; error?: string; rel_rms?: number }>;
  geometry: CAGeometry; diagnostics: Diagnostic[]; warnings: string[]; errors: string[]; image: { width: number; height: number } | null;
  params: Record<string, unknown>; uncertainty_note: string; manual_correction: boolean; suggested_baseline: Pt[] | null;
  overlay_png_base64?: string | null; auto_result?: CAResult;
};
export type CARun = {
  id: number; specimen_id: number; experiment_id: number | null; image_artifact_id: number; overlay_artifact_id: number | null; method: string;
  status: string; left_deg: number | null; right_deg: number | null; mean_deg: number | null; classification: string | null;
  analysis_params: Record<string, unknown>; diagnostics: Partial<CAResult>; warnings: string[]; auto_result: Partial<CAResult> | null;
  algorithm_version: string; liquid: string; droplet_volume_ul: number | null; captured_at: string | null; measured_at: string;
  rejection_reason: string | null; notes: string | null; is_demo: boolean; created_at: string;
};
export type Metric = {
  id?: number; name: string; label: string; value: number | null; unit: string; origin: string; formula: string; parameters: Record<string, unknown>;
  assumptions: string[]; warnings: string[]; valid: boolean; superseded?: boolean; analysis_id?: number;
};
export type CorrosionRun = {
  id: number; specimen_id: number; experiment_id: number | null; raw_artifact_id: number; processed_artifact_id: number; method: "ocp" | "lpr" | "pdp" | "eis";
  column_mapping: Record<string, string>; units: Record<string, string>; import_meta: Record<string, unknown>; parser_warnings: string[];
  exposed_area_cm2: number | null; area_source: string | null; reference_electrode: string | null; instrument: string | null; n_points: number;
  analysis_status: string; notes: string | null; is_demo: boolean; created_at: string; metrics?: Metric[];
};
export type AuditItem = { id: number; action: string; summary: string; details: Record<string, unknown>; created_at: string };
