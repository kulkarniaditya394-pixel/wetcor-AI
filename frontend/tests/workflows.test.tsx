import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CorrosionPage from "@/app/corrosion/page";
import MLStudio from "@/app/ml-studio/page";
import { ExperimentForm, SpecimenForm } from "@/components/RecordForms";
import { mockFetch } from "./helpers";

const specimens = { items: [{ id: 1, code: "MS-01", material: "Mild steel", exposed_area_cm2: 1 }], total: 1, page: 1, page_size: 500 };

describe("specimen and experiment forms", () => {
  it("validates required identifiers and the reserved demo prefix", async () => {
    const calls = mockFetch({});
    render(<SpecimenForm onSaved={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Register specimen" }));
    expect(await screen.findByText("Material is required.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Specimen ID/), { target: { value: "DEMO-7" } });
    fireEvent.click(screen.getByRole("button", { name: "Register specimen" }));
    expect(await screen.findByText(/reserved for synthetic demo/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("submits typed values and leaves unknown fields empty", async () => {
    let body: Record<string, unknown> = {};
    mockFetch({ "POST /api/specimens": (init?: RequestInit) => { body = JSON.parse(String(init?.body)); return { id: 9, ...body }; } });
    let saved = 0;
    render(<SpecimenForm onSaved={(s) => (saved = s.id)} />);
    fireEvent.change(screen.getByLabelText(/Specimen ID/), { target: { value: "MS-02" } });
    fireEvent.change(screen.getByLabelText(/Material/), { target: { value: "Mild steel" } });
    fireEvent.change(screen.getByLabelText(/Exposed electrode area/), { target: { value: "1.25" } });
    fireEvent.click(screen.getByRole("button", { name: "Register specimen" }));
    await waitFor(() => expect(saved).toBe(9));
    expect(body).toMatchObject({ code: "MS-02", material: "Mild steel", exposed_area_cm2: 1.25, roughness_ra_um: null, surface_preparation: null });
  });

  it("saves an experiment linked to the chosen specimen", async () => {
    let body: Record<string, unknown> = {};
    mockFetch({ "GET /api/specimens": specimens, "POST /api/experiments": (init?: RequestInit) => { body = JSON.parse(String(init?.body)); return { id: 4, ...body }; } });
    let saved = 0;
    render(<ExperimentForm onSaved={(e) => (saved = e.id)} />);
    await screen.findByRole("option", { name: /MS-01/ });
    fireEvent.change(screen.getByLabelText(/Experiment ID/), { target: { value: "EXP-1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Specimen" }), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText(/Temperature/), { target: { value: "25" } });
    fireEvent.click(screen.getByRole("button", { name: "Create experiment" }));
    await waitFor(() => expect(saved).toBe(4));
    expect(body).toMatchObject({ code: "EXP-1", specimen_id: 1, temperature_c: 25, electrolyte: "NaCl", concentration_value: 3.5 });
  });
});

const methods = {
  methods: { ocp: "Open-circuit potential", lpr: "Linear polarisation resistance", pdp: "Potentiodynamic polarisation", eis: "Electrochemical impedance spectroscopy" },
  required: { ocp: [["time"], ["potential"]], lpr: [["potential"], ["current", "current_density"]], pdp: [["potential"], ["current", "current_density"]], eis: [["frequency"], ["z_real"], ["z_imag"]] },
  allowed_roles: { ocp: ["potential", "time"], lpr: ["current", "current_density", "potential", "time"], pdp: ["current", "current_density", "potential", "time"], eis: ["frequency", "phase", "z_imag", "z_mod", "z_real"] },
  units: { potential: { V: 1, mV: 0.001 }, current: { A: 1, mA: 0.001, uA: 1e-6 }, current_density: { "A/cm2": 1 }, time: { s: 1 }, frequency: { Hz: 1 }, impedance: { ohm: 1 }, phase: { deg: 1 } },
};
const preview = {
  filename: "lpr.csv", size_bytes: 100, encoding: "utf-8", delimiter: "comma", decimal_comma: false, columns: ["E", "I"], units_row: null, n_rows: 3,
  metadata: {}, warnings: [], preview_rows: [[-650, 1.2], [-649, 1.4], [-648, 1.6]], raw_head: ["E,I", "-650,1.2"],
  suggestion: { mapping: { potential: "E", current: "I" }, units: { potential: null, current: null }, imag_convention: "as_is", suggested_method: null },
  columns_data: { E: [-650, -649, -648], I: [1.2, 1.4, 1.6] },
};

describe("corrosion import wizard", () => {
  it("requires an explicit method and unit for every mapped column before import", async () => {
    let imported: Record<string, unknown> | null = null;
    mockFetch({
      "GET /api/corrosion/methods": methods, "GET /api/corrosion/runs": [], "GET /api/specimens": specimens, "GET /api/experiments": { items: [], total: 0, page: 1, page_size: 500 },
      "POST /api/corrosion/import/preview": preview,
      "POST /api/corrosion/import": (init?: RequestInit) => { imported = JSON.parse(String((init?.body as FormData).get("meta"))); return { id: 12 }; },
    });
    render(<CorrosionPage />);
    expect(screen.getByText("Awaiting file")).toBeInTheDocument();
    const input = screen.getByLabelText("Choose measurement file");
    fireEvent.change(input, { target: { files: [new File(["E,I\n-650,1.2"], "lpr.csv", { type: "text/csv" })] } });
    expect(await screen.findByText("2 · Preview")).toBeInTheDocument();
    expect(screen.getByText("Columns require mapping")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("radio", { name: /LPR/ }));
    expect(screen.getByText(/Select the unit for potential/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import run" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Unit for Potential" }), { target: { value: "mV" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Unit for Current (total)" }), { target: { value: "uA" } });
    await screen.findByRole("option", { name: /MS-01/ });
    fireEvent.change(screen.getByRole("combobox", { name: /Specimen ID/ }), { target: { value: "1" } });
    expect(await screen.findByText("Ready to import")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Preview plot of mapped data" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import run" }));
    await waitFor(() => expect(imported).not.toBeNull());
    expect(imported).toMatchObject({ method: "lpr", mapping: { potential: "E", current: "I" }, units: { potential: "mV", current: "uA" }, specimen_id: 1 });
  });
});

const notReady = {
  readiness: { target: "i_corr", target_unit: "uA/cm2", n_records: 1, n_groups: 1, demo_records: 0, level: "insufficient", can_train: false, validated_badge: false,
    blocking: ["1 independent specimen group(s); at least 4 are required for grouped cross-validation (configurable policy)."], advisories: [], n_splits: 0, excluded: [], features: {} },
};
const options = { targets: { i_corr: { label: "Corrosion current density i_corr", unit: "uA/cm2", explain: "x" } }, features: { material: { kind: "categorical", label: "Specimen material" }, contact_angle_deg: { kind: "numeric", label: "CA" } }, wettability_feature: "contact_angle_deg" };

describe("ML studio", () => {
  it("disables training and explains why when the dataset is insufficient", async () => {
    mockFetch({ "GET /api/ml/options": options, "GET /api/ml/runs": [], "POST /api/ml/readiness-check": notReady });
    render(<MLStudio />);
    expect(await screen.findByText(/at least 4 are required/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Train & compare/ })).toBeDisabled();
    expect(screen.getByText("insufficient")).toBeInTheDocument();
    expect(screen.getByText(/No metrics are shown until an evaluation has actually run/)).toBeInTheDocument();
  });

  it("shows a training failure returned by the backend", async () => {
    const ready = { readiness: { ...notReady.readiness, level: "exploratory", can_train: true, blocking: [], n_groups: 6, n_records: 6, n_splits: 5 } };
    mockFetch({ "GET /api/ml/options": options, "GET /api/ml/runs": [], "POST /api/ml/readiness-check": ready, "POST /api/ml/train": [422, { detail: "Target leakage: rp are electrochemical outputs" }] });
    render(<MLStudio />);
    const btn = await screen.findByRole("button", { name: /Train & compare/ });
    await waitFor(() => expect(btn).toBeEnabled());
    fireEvent.click(btn);
    const alert = await screen.findByText("Training refused");
    expect(within(alert.closest("[role=alert]") as HTMLElement).getByText(/Target leakage/)).toBeInTheDocument();
  });
});
