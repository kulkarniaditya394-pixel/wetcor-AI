import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ShowcasePage from "@/app/showcase/page";
import { mockFetch } from "./helpers";

const manifest = {
  title: "Showcase: wettability and corrosion of a steel specimen", summary: "Pre-computed test.",
  contact_angle: { source: { title: "t", author: "a", url: "u", licence: "CC BY-SA 4.0", licence_url: "l", substrate: "s" }, preprocessing: [], correction_reason: "r",
    reference: { source: "x", left_deg: 114.95, right_deg: 114.29 } },
};

describe("showcase", () => {
  it("is only created by an explicit user action", async () => {
    let loaded = false;
    const calls = mockFetch({
      "GET /api/demo/showcase": () => ({ loaded, manifest, showcase: null }),
      "POST /api/demo/showcase/load": () => { loaded = true; return {}; },
    });
    render(<ShowcasePage />);
    expect(await screen.findByText("Showcase example not loaded")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Load showcase example" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === "/api/demo/showcase/load")).toBe(true));
  });
});
