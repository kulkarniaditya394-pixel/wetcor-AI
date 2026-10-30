import { vi } from "vitest";

/** Route-based fetch mock: keys are "METHOD path-prefix"; values return JSON bodies or [status, body]. */
export function mockFetch(routes: Record<string, unknown | ((init?: RequestInit) => unknown)>) {
  const calls: { method: string; path: string; init?: RequestInit }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname + url.search;
    calls.push({ method, path, init });
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => {
      const [m, p] = k.split(" ");
      return m === method && path.startsWith(p);
    });
    if (!key) return new Response(JSON.stringify({ detail: `unmocked ${method} ${path}` }), { status: 404, headers: { "content-type": "application/json" } });
    let body = routes[key];
    if (typeof body === "function") body = (body as (i?: RequestInit) => unknown)(init);
    const [status, payload] = Array.isArray(body) && typeof body[0] === "number" ? (body as [number, unknown]) : [200, body];
    return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}
