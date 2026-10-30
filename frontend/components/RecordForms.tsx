"use client";

import { useState } from "react";
import { api, type Experiment, type Page, type Specimen } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { experimentSchema, specimenSchema, validate } from "@/schemas/forms";
import { Alert, Button, Field, LabeledInput, Select, Textarea } from "./ui";

export function SpecimenForm({ onSaved, onCancel }: { onSaved: (s: Specimen) => void; onCancel?: () => void }) {
  const [v, setV] = useState<Record<string, string>>({ code: "", material: "", surface_preparation: "", dimensions: "50 x 25 x 2 mm", exposed_area_cm2: "", roughness_ra_um: "", batch_source: "", notes: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const f = (k: string, label: string, extra: Record<string, unknown> = {}) => (
    <LabeledInput label={label} value={v[k]} error={errors[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} {...extra} />
  );
  return (
    <form
      noValidate
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={async (e) => {
        e.preventDefault();
        const { data, errors } = validate(specimenSchema, v);
        setErrors(errors);
        if (!data) return;
        setBusy(true);
        setErr(null);
        try {
          onSaved(await api<Specimen>("/api/specimens", { method: "POST", json: data }));
        } catch (ex) {
          setErr((ex as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      {f("code", "Specimen ID", { required: true, placeholder: "e.g. MS-01" })}
      {f("material", "Material", { required: true, placeholder: "e.g. Mild steel IS 2062" })}
      {f("surface_preparation", "Surface preparation / treatment", { placeholder: "e.g. polished to 1200 grit" })}
      {f("dimensions", "Dimensions")}
      {f("exposed_area_cm2", "Exposed electrode area (cm²)", { type: "number", step: "any", hint: "Needed to convert current to current density." })}
      {f("roughness_ra_um", "Roughness Ra (µm)", { type: "number", step: "any", hint: "Optional." })}
      {f("batch_source", "Batch / source")}
      <div className="sm:col-span-2"><Field label="Notes"><Textarea aria-label="Specimen notes" value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></Field></div>
      {err && <div className="sm:col-span-2"><Alert tone="bad">{err}</Alert></div>}
      <div className="flex gap-2 sm:col-span-2">
        <Button type="submit" variant="primary" busy={busy}>Register specimen</Button>
        {onCancel && <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>}
      </div>
    </form>
  );
}

export function ExperimentForm({ onSaved, onCancel, specimenId }: { onSaved: (e: Experiment) => void; onCancel?: () => void; specimenId?: number }) {
  const specs = useApi<Page<Specimen>>("/api/specimens?page_size=500&sort=code");
  const [v, setV] = useState<Record<string, string>>({ code: "", specimen_id: specimenId ? String(specimenId) : "", experiment_type: "combined", performed_at: "", operator: "",
    electrolyte: "NaCl", concentration_value: "3.5", concentration_unit: "wt%", temperature_c: "", instrument: "", reference_electrode: "", procedure: "", notes: "", status: "in_progress" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const f = (k: string, label: string, extra: Record<string, unknown> = {}) => (
    <LabeledInput label={label} value={v[k]} error={errors[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} {...extra} />
  );
  return (
    <form
      noValidate
      className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3"
      onSubmit={async (e) => {
        e.preventDefault();
        const { data, errors } = validate(experimentSchema, v);
        setErrors(errors);
        if (!data) return;
        setBusy(true);
        setErr(null);
        try {
          onSaved(await api<Experiment>("/api/experiments", { method: "POST", json: { ...data, performed_at: data.performed_at ? new Date(data.performed_at).toISOString() : null } }));
        } catch (ex) {
          setErr((ex as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      {f("code", "Experiment ID", { required: true, placeholder: "e.g. EXP-2026-01" })}
      <Field label="Specimen" required error={errors.specimen_id}>
        <Select aria-label="Specimen" value={v.specimen_id} onChange={(e) => setV({ ...v, specimen_id: e.target.value })}>
          <option value="">Select…</option>
          {(specs.data?.items ?? []).map((s) => <option key={s.id} value={s.id}>{s.code} — {s.material}</option>)}
        </Select>
      </Field>
      <Field label="Type">
        <Select aria-label="Experiment type" value={v.experiment_type} onChange={(e) => setV({ ...v, experiment_type: e.target.value })}>
          <option value="combined">Combined (wettability + corrosion)</option><option value="wettability">Wettability only</option><option value="corrosion">Corrosion only</option>
        </Select>
      </Field>
      {f("performed_at", "Date and time", { type: "datetime-local" })}
      {f("operator", "Operator")}
      {f("electrolyte", "Electrolyte")}
      {f("concentration_value", "Concentration", { type: "number", step: "any" })}
      {f("concentration_unit", "Concentration unit", { placeholder: "wt%, mol/L" })}
      {f("temperature_c", "Temperature (°C)", { type: "number", step: "any" })}
      {f("instrument", "Instrument")}
      {f("reference_electrode", "Reference electrode", { placeholder: "SCE, Ag/AgCl…" })}
      <Field label="Status">
        <Select aria-label="Status" value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}>
          <option value="planned">planned</option><option value="in_progress">in progress</option><option value="complete">complete</option><option value="invalid">invalid</option>
        </Select>
      </Field>
      <div className="sm:col-span-2 lg:col-span-3"><Field label="Procedure / settings"><Textarea aria-label="Procedure" value={v.procedure} onChange={(e) => setV({ ...v, procedure: e.target.value })} placeholder="Scan rate, potential window, stabilisation time…" /></Field></div>
      {err && <div className="sm:col-span-2 lg:col-span-3"><Alert tone="bad">{err}</Alert></div>}
      <div className="flex gap-2 sm:col-span-2 lg:col-span-3">
        <Button type="submit" variant="primary" busy={busy}>Create experiment</Button>
        {onCancel && <Button type="button" variant="ghost" onClick={onCancel}>Cancel</Button>}
      </div>
    </form>
  );
}
