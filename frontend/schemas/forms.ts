import { z } from "zod";

const blankToNull = (v: unknown) => (v === "" || v === undefined ? null : v);
const optText = (max = 200) => z.preprocess(blankToNull, z.string().trim().max(max).nullable());
const optNum = (min: number, max: number, msg: string) => z.preprocess((v) => (v === "" || v == null ? null : Number(v)), z.number({ error: "Enter a number" }).min(min, msg).max(max, msg).nullable());

export const code = z
  .string()
  .trim()
  .regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/, "Use letters, digits, '.', '_' or '-' (max 64), starting with a letter or digit.")
  .refine((v) => !v.toUpperCase().startsWith("DEMO-"), "The 'DEMO-' prefix is reserved for synthetic demo records.");

export const specimenSchema = z.object({
  code,
  material: z.string().trim().min(1, "Material is required.").max(120),
  batch_source: optText(),
  dimensions: optText(),
  surface_preparation: optText(),
  roughness_ra_um: optNum(0, 1000, "Ra must be between 0 and 1000 µm."),
  exposed_area_cm2: z.preprocess((v) => (v === "" || v == null ? null : Number(v)), z.number({ error: "Enter a number" }).positive("Area must be greater than 0.").max(10000).nullable()),
  notes: optText(5000),
});

export const experimentSchema = z.object({
  code,
  specimen_id: z.preprocess((v) => (v === "" || v == null ? undefined : Number(v)), z.number({ error: "Select a specimen." })),
  experiment_type: z.enum(["wettability", "corrosion", "combined"]),
  performed_at: z.preprocess(blankToNull, z.string().nullable()),
  operator: optText(120),
  electrolyte: optText(120),
  concentration_value: optNum(0, 1e6, "Concentration must be ≥ 0."),
  concentration_unit: optText(20),
  temperature_c: optNum(-50, 300, "Temperature must be between −50 and 300 °C."),
  instrument: optText(),
  reference_electrode: optText(120),
  procedure: optText(10000),
  notes: optText(5000),
  status: z.enum(["planned", "in_progress", "complete", "invalid"]),
});

export function validate<T extends z.ZodTypeAny>(schema: T, values: Record<string, unknown>): { data: z.infer<T> | null; errors: Record<string, string> } {
  const r = schema.safeParse(values);
  if (r.success) return { data: r.data, errors: {} };
  const errors: Record<string, string> = {};
  for (const issue of r.error.issues) {
    const k = String(issue.path[0] ?? "form");
    errors[k] ??= issue.message;
  }
  return { data: null, errors };
}
