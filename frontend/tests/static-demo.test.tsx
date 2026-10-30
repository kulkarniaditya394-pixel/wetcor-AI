import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ShowcasePage from "@/app/showcase/page";
import { Sidebar } from "@/components/Sidebar";
import { StaticGate } from "@/components/StaticGate";
import { nav } from "./setup";

afterEach(() => vi.unstubAllEnvs());

const snapshot = {
  manifest: { title: "Showcase: steel", summary: "s", contact_angle: { source: { title: "t", author: "a", url: "u", licence: "CC BY-SA 4.0", licence_url: "l", substrate: "x" }, preprocessing: [], correction_reason: "r", reference: { source: "x", left_deg: 114.95, right_deg: 114.29 } } },
  showcase: { specimen_id: 1, experiment_id: 1, contact_angle_run_ids: [1], corrosion_runs: [{ id: 2, method: "pdp" }, { id: 3, method: "ocp" }] },
  spec: { specimen: { code: "DEMO-SHOWCASE-01", material: "Mild steel", surface_preparation: null, dimensions: null, exposed_area_cm2: 1, roughness_ra_um: null }, experiments: [{ code: "E1", electrolyte: "NaCl", concentration_value: 3.5, concentration_unit: "wt%", temperature_c: 25, reference_electrode: "SCE", procedure: "p" }], artifacts: [] },
  ca: { mean_deg: 111.2, left_deg: 112.6, right_deg: 109.9, classification: "hydrophobic", method: "manual_corrected", algorithm_version: "ca-1.0.0", diagnostics: { diagnostics: [] }, auto_result: null },
  pdp: { metrics: [], current_analysis: null, raw_file: { sha256: "a".repeat(64) } }, pdpData: { method: "pdp", n_points: 0, data: {} },
  ocp: { metrics: [], current_analysis: null, raw_file: { sha256: "b".repeat(64) } }, ocpData: { method: "ocp", n_points: 0, data: {} },
  images: { source: "/showcase-static/source.png", overlay: "/showcase-static/overlay.png" }, report: "/showcase-static/report.html",
};

describe("hosted static demo mode", () => {
  it("offers the showcase and the two labs, and never polls a backend", async () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC_DEMO", "1");
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    nav.pathname = "/showcase";
    render(<Sidebar />);
    expect(screen.getAllByRole("link").map((a) => a.textContent)).toContain("Showcase");
    expect(screen.getByRole("link", { name: "Wettability Lab" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Corrosion Lab" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "ML Studio" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Experiments" })).not.toBeInTheDocument();
    expect(screen.getByText("Hosted site")).toBeInTheDocument();
    expect(f).not.toHaveBeenCalled();
  });

  it("explains that database pages need the local app, but lets the showcase and labs through", () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC_DEMO", "1");
    nav.pathname = "/experiments";
    const { unmount } = render(<StaticGate><div>live page</div></StaticGate>);
    expect(screen.getByText("This page needs the local app")).toBeInTheDocument();
    expect(screen.queryByText("live page")).not.toBeInTheDocument();
    unmount();
    for (const path of ["/showcase", "/wettability", "/corrosion"]) {
      nav.pathname = path;
      const r = render(<StaticGate><div>live page</div></StaticGate>);
      expect(screen.getByText("live page")).toBeInTheDocument();
      r.unmount();
    }
    nav.pathname = "/wettability/0"; // record pages need the database
    render(<StaticGate><div>live page</div></StaticGate>);
    expect(screen.queryByText("live page")).not.toBeInTheDocument();
  });

  it("is a no-op in normal (local) mode", () => {
    nav.pathname = "/corrosion";
    render(<StaticGate><div>live page</div></StaticGate>);
    expect(screen.getByText("live page")).toBeInTheDocument();
  });

  it("renders the showcase from the bundled snapshot with no API call", async () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC_DEMO", "1");
    const f = vi.fn(async (url: string) => {
      expect(String(url)).toBe("/showcase-static/snapshot.json");
      return new Response(JSON.stringify(snapshot), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", f);
    render(<ShowcasePage />);
    expect((await screen.findAllByText("111.2°")).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Printable report/ })).toHaveAttribute("href", "/showcase-static/report.html");
    expect(screen.queryByRole("button", { name: "Load showcase example" })).not.toBeInTheDocument();
    expect(screen.getByAltText(/WETCOR AI annotated analysis/)).toHaveAttribute("src", "/showcase-static/overlay.png");
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
  });
});

describe("static demo root", () => {
  it("shows the showcase (not the gate) at /", () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC_DEMO", "1");
    nav.pathname = "/";
    render(<StaticGate><div>showcase here</div></StaticGate>);
    expect(screen.getByText("showcase here")).toBeInTheDocument();
  });
});

describe("hosted engine routing", () => {
  it("sends analysis calls to the in-browser engine instead of an HTTP backend", async () => {
    vi.stubEnv("NEXT_PUBLIC_STATIC_DEMO", "1");
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    const { engineRoute } = await import("@/lib/engine");
    await expect(engineRoute("/api/specimens", { method: "GET" })).rejects.toThrow(/not available in the hosted demo/);
    await expect(engineRoute("/api/wettability/analyze", { method: "POST", body: new FormData() })).rejects.toThrow(/Missing 'image' file/);
    expect(f).not.toHaveBeenCalled();
  });
});
