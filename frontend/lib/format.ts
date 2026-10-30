/** Number/date formatting. Backend timestamps are UTC without a zone suffix. */
export function toDate(s: string | null | undefined): Date | null {
  if (!s) return null;
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
}

export function fmtDate(s: string | null | undefined, withTime = true): string {
  const d = toDate(s);
  if (!d || isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, withTime ? { dateStyle: "medium", timeStyle: "short" } : { dateStyle: "medium" });
}

export function fmtNum(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (v !== 0 && (Math.abs(v) >= 1e5 || Math.abs(v) < 1e-3)) return v.toExponential(digits - 1);
  return Number(v.toPrecision(digits)).toString();
}

export function fmtDeg(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(1)}°`;
}

export const UNIT_LABEL: Record<string, string> = {
  uA: "µA", "uA/cm2": "µA/cm²", "A/cm2": "A/cm²", "mA/cm2": "mA/cm²", "nA/cm2": "nA/cm²", "A/m2": "A/m²", "mA/m2": "mA/m²",
  ohm: "Ω", kohm: "kΩ", Mohm: "MΩ", mohm: "mΩ", "ohm*cm2": "Ω·cm²", cm2: "cm²", mm2: "mm²", m2: "m²", deg: "°",
};
export const unit = (u: string | null | undefined) =>
  !u ? "" : UNIT_LABEL[u] ?? u.replace("uA/cm2", "µA/cm²").replace("ohm*cm2", "Ω·cm²").replace("A/cm2", "A/cm²");
