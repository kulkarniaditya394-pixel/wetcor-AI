"use client";

import Link from "next/link";
import { useId } from "react";
import { useApi } from "@/hooks/useApi";
import type { Experiment, Page, Specimen } from "@/lib/api";
import { Field, Select } from "./ui";

export function SpecimenPicker({ specimenId, experimentId, onChange, error }: {
  specimenId: number | null; experimentId: number | null; onChange: (s: number | null, e: number | null, spec?: Specimen) => void; error?: string;
}) {
  const sid = useId();
  const eid = useId();
  const specs = useApi<Page<Specimen>>("/api/specimens?page_size=500&sort=code");
  const exps = useApi<Page<Experiment>>(specimenId ? `/api/experiments?specimen_id=${specimenId}&page_size=500` : null);
  const items = specs.data?.items ?? [];
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="Specimen ID" required htmlFor={sid} error={error}
        hint={items.length === 0 && !specs.loading ? <>No specimens yet. <Link className="text-accent underline" href="/experiments?new=specimen">Register a specimen</Link>.</> : undefined}>
        <Select id={sid} value={specimenId ?? ""} aria-invalid={!!error || undefined}
          onChange={(e) => {
            const id = e.target.value ? Number(e.target.value) : null;
            onChange(id, null, items.find((s) => s.id === id));
          }}>
          <option value="">{specs.loading ? "Loading…" : "Select specimen…"}</option>
          {items.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.material}</option>)}
        </Select>
      </Field>
      <Field label="Experiment (optional)" htmlFor={eid} hint={specimenId && exps.data?.items.length === 0 ? "No experiments for this specimen yet." : undefined}>
        <Select id={eid} value={experimentId ?? ""} disabled={!specimenId} onChange={(e) => onChange(specimenId, e.target.value ? Number(e.target.value) : null, items.find((s) => s.id === specimenId))}>
          <option value="">None</option>
          {(exps.data?.items ?? []).map((x) => <option key={x.id} value={x.id}>{x.code} ({x.experiment_type})</option>)}
        </Select>
      </Field>
    </div>
  );
}
