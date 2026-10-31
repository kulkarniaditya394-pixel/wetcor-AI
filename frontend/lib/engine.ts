/** Client for the in-browser analysis engine (Pyodide web worker). Used only by the hosted static site. */
import { ApiError } from "./api";

export type EngineState = { state: "idle" | "loading" | "ready" | "error"; stage: number; of: number; message: string };

type EngineResponse = { ok: boolean; result?: unknown; status?: number; detail?: string };

let worker: Worker | null = null;
let seq = 0;
const pending = new Map<number, (r: EngineResponse) => void>();
const listeners = new Set<(s: EngineState) => void>();
let current: EngineState = { state: "idle", stage: 0, of: 4, message: "" };
let readyPromise: Promise<void> | null = null;

function set(next: Partial<EngineState>) {
  current = { ...current, ...next };
  listeners.forEach((l) => l(current));
}

export const engineState = () => current;
export function subscribeEngine(fn: (s: EngineState) => void) {
  listeners.add(fn);
  return () => void listeners.delete(fn);
}

/** Start loading the engine (idempotent). */
export function ensureEngine(): Promise<void> {
  if (readyPromise) return readyPromise;
  readyPromise = new Promise<void>((resolve, reject) => {
    set({ state: "loading", stage: 0, message: "Starting the analysis engine" });
    worker = new Worker("/engine/worker.js", { type: "module" });
    worker.onmessage = (e: MessageEvent) => {
      const m = e.data;
      if (m.type === "progress") set({ state: "loading", stage: m.stage, of: m.of, message: m.message });
      else if (m.type === "ready") {
        set({ state: "ready", stage: 4, message: `Python ${m.python}` });
        resolve();
      } else if (m.type === "error") {
        set({ state: "error", message: m.message });
        readyPromise = null;
        reject(new Error(m.message));
      } else if (m.type === "result") {
        pending.get(m.id)?.(m.response);
        pending.delete(m.id);
      }
    };
    worker.onerror = (e) => {
      set({ state: "error", message: e.message || "Worker failed to start" });
      readyPromise = null;
      reject(new Error(e.message));
    };
  });
  return readyPromise;
}

/** Run an engine function; resolves with its result or throws ApiError like the HTTP client would. */
export async function engineCall<T>(fn: string, args: Record<string, unknown> = {}, blob?: ArrayBuffer): Promise<T> {
  try {
    await ensureEngine();
  } catch (e) {
    throw new ApiError(503, `The in-browser analysis engine could not start: ${(e as Error).message}. It downloads Python from the jsDelivr CDN; check your connection and reload.`);
  }
  const id = ++seq;
  const response = await new Promise<EngineResponse>((resolve) => {
    pending.set(id, resolve);
    worker!.postMessage({ id, fn, args, blob }, blob ? [blob] : []);
  });
  if (!response.ok) throw new ApiError(response.status ?? 500, response.detail ?? "Engine error");
  return response.result as T;
}

/** Map the app's REST paths onto engine functions so existing pages work unchanged in the hosted site. */
export async function engineRoute(path: string, init: { method?: string; body?: BodyInit | null; json?: unknown }): Promise<{ value: unknown }> {
  const method = (init.method ?? "GET").toUpperCase();
  const route = path.split("?")[0];
  const fd = init.body instanceof FormData ? init.body : null;
  const file = async (key: string) => {
    const f = fd?.get(key);
    if (!(f instanceof Blob)) throw new ApiError(422, `Missing '${key}' file.`);
    return { buf: await f.arrayBuffer(), name: f instanceof File ? f.name : "" };
  };
  const json = (key: string) => {
    const v = fd?.get(key);
    return typeof v === "string" && v ? JSON.parse(v) : undefined;
  };
  if (method === "POST" && route === "/api/corrosion/rig/parse") return { value: await engineCall("rig_parse", init.json as Record<string, unknown>) };
  if (method === "POST" && route === "/api/corrosion/rig/analyze") return { value: await engineCall("rig_analyze", init.json as Record<string, unknown>) };
  if (method === "POST" && route === "/api/wettability/analyze") {
    const { buf } = await file("image");
    return { value: await engineCall("wettability_analyze", { params: json("params") ?? {} }, buf) };
  }
  if (method === "GET" && route === "/api/corrosion/methods") return { value: await engineCall("corrosion_methods") };
  if (method === "GET" && route === "/api/materials") return { value: ((await engineCall("corrosion_methods")) as { materials: unknown }).materials };
  if (method === "POST" && route === "/api/corrosion/import/preview") {
    const { buf, name } = await file("file");
    return { value: await engineCall("corrosion_preview", { filename: name }, buf) };
  }
  if (method === "POST" && route === "/api/corrosion/quick") {
    const { buf } = await file("file");
    const meta = json("meta");
    return { value: await engineCall("corrosion_quick", { meta, params: json("params") ?? {}, material: json("material") ?? null, reference_electrode: meta?.reference_electrode ?? null }, buf) };
  }
  throw new ApiError(404, "This function is not available in the hosted demo; it needs the local app (database, ML and saved records).");
}
