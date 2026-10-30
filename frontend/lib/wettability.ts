import type { Tone } from "@/components/ui";

export const CA_NOTE =
  "Contact-angle classification describes the measured water wettability. It does not independently establish corrosion resistance or corrosion rate.";

export const classTone = (label?: string | null): Tone =>
  label === "hydrophilic" ? "calc" : label === "hydrophobic" ? "accent" : label === "boundary" ? "warn" : "neutral";
