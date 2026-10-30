import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Dashboard from "@/app/dashboard/page";
import Reports from "@/app/reports/page";
import { Plot } from "@/components/Plot";
import { Sidebar } from "@/components/Sidebar";
import { mockFetch } from "./helpers";
import { nav } from "./setup";

const zero = { specimens: 0, contact_angle_runs: 0, corrosion_runs: 0, experiments: 0, completed_experiments: 0, ml_eligible_records: 0 };

describe("navigation", () => {
  it("lists all sections and marks the active one", async () => {
    nav.pathname = "/corrosion/runs/3";
    mockFetch({ "GET /api/health": { status: "ok", database: "ok" } });
    render(<Sidebar />);
    for (const label of ["Overview", "Wettability Lab", "Corrosion Lab", "Experiments", "ML Studio", "Reports", "Settings"]) expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Corrosion Lab" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
    await waitFor(() => expect(screen.getByText("Backend connected")).toBeInTheDocument());
  });

  it("never shows connected when the health check fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    render(<Sidebar />);
    expect(screen.queryByText("Backend connected")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Backend unreachable")).toBeInTheDocument());
  });
});

describe("dashboard", () => {
  it("shows an empty state with next actions when no data exist", async () => {
    mockFetch({ "GET /api/dashboard": { real: zero, demo: zero, ml_runs: 0, completeness: { specimens_total: 0, with_contact_angle: 0, with_corrosion: 0, with_both: 0, with_exposed_area: 0 }, recent_experiments: [], activity: [] } });
    render(<Dashboard />);
    expect(await screen.findByText("No laboratory data yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register first specimen" })).toBeInTheDocument();
    expect(screen.getByText("ML-eligible records").parentElement).toHaveTextContent("0");
  });

  it("reports demo data separately from real counts", async () => {
    mockFetch({ "GET /api/dashboard": { real: zero, demo: { ...zero, specimens: 10 }, ml_runs: 0, completeness: { specimens_total: 0, with_contact_angle: 0, with_corrosion: 0, with_both: 0, with_exposed_area: 0 }, recent_experiments: [], activity: [] } });
    render(<Dashboard />);
    expect(await screen.findByText(/Demo workspace loaded: 10 specimens/)).toBeInTheDocument();
    expect(screen.getByText("Specimens").parentElement).toHaveTextContent("0");
  });
});

describe("plots and exports", () => {
  it("renders plot data through plotly", async () => {
    const Plotly = (await import("plotly.js-dist-min")).default;
    render(<Plot data={[{ x: [1, 2], y: [3, 4] }]} label="Test plot" />);
    expect(screen.getByRole("img", { name: "Test plot" })).toBeInTheDocument();
    await waitFor(() => expect(Plotly.react).toHaveBeenCalled());
    const [, data] = vi.mocked(Plotly.react).mock.calls.at(-1)!;
    expect(data).toEqual([{ x: [1, 2], y: [3, 4] }]);
  });

  it("links every CSV export to the backend", async () => {
    mockFetch({ "GET /api/experiments": { items: [], total: 0, page: 1, page_size: 500 }, "GET /api/ml/runs": [] });
    render(<Reports />);
    for (const kind of ["specimens", "contact_angles", "metrics", "dataset", "ml_predictions"]) {
      const btn = screen.getByRole("button", { name: `${kind}.csv` });
      expect(btn.closest("a")).toHaveAttribute("href", `http://127.0.0.1:8100/api/exports/${kind}.csv`);
    }
    expect(await screen.findByText("No ML comparisons have been trained yet.")).toBeInTheDocument();
  });
});
