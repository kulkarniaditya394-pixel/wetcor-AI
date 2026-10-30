import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, vi } from "vitest";

export const nav = { pathname: "/dashboard", push: vi.fn(), replace: vi.fn(), params: {} as Record<string, string>, search: new URLSearchParams() };

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: nav.push, replace: nav.replace, back: vi.fn() }),
  useParams: () => nav.params,
  useSearchParams: () => nav.search,
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => createElement("a", { href, ...rest }, children),
}));

vi.mock("plotly.js-dist-min", () => ({ default: { react: vi.fn(async () => undefined), purge: vi.fn(), Plots: { resize: vi.fn() } } }));

class RO {
  observe() {}
  disconnect() {}
  unobserve() {}
}
vi.stubGlobal("ResizeObserver", RO);

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.stubGlobal("ResizeObserver", RO);
  nav.push.mockReset();
  nav.replace.mockReset();
  nav.search = new URLSearchParams();
});
