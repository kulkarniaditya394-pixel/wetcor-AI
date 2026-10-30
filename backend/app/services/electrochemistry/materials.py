"""Reference material profiles for the corrosion-rate conversion (pure metals only).

EW = standard atomic weight / assumed oxidation state n (single dissolving element). Densities are
room-temperature handbook values for the pure metal. Alloys are deliberately absent: their
equivalent weight depends on composition and on valence assumptions (see ASTM G102) and must be
supplied by the user with its source.
"""
from __future__ import annotations

PROVENANCE = ("Pure-metal reference profile: EW = IUPAC standard atomic weight / assumed valence n; density = handbook value "
              "for the pure metal at ~20 C. Verify against your specimen; not valid for alloys or coated surfaces.")

PROFILES: dict[str, dict] = {
    "Fe": {"label": "Iron, Fe -> Fe2+ (often used as an approximation for plain carbon steel; verify)", "atomic_weight": 55.845, "valence": 2, "density_g_cm3": 7.874},
    "Al": {"label": "Aluminium, Al -> Al3+", "atomic_weight": 26.982, "valence": 3, "density_g_cm3": 2.699},
    "Cu": {"label": "Copper, Cu -> Cu2+", "atomic_weight": 63.546, "valence": 2, "density_g_cm3": 8.96},
    "Zn": {"label": "Zinc, Zn -> Zn2+", "atomic_weight": 65.38, "valence": 2, "density_g_cm3": 7.134},
    "Ni": {"label": "Nickel, Ni -> Ni2+", "atomic_weight": 58.693, "valence": 2, "density_g_cm3": 8.908},
    "Mg": {"label": "Magnesium, Mg -> Mg2+", "atomic_weight": 24.305, "valence": 2, "density_g_cm3": 1.738},
}


def profile(key: str) -> dict:
    p = PROFILES[key]
    return {"key": key, "label": p["label"], "equivalent_weight_g_eq": round(p["atomic_weight"] / p["valence"], 4),
            "density_g_cm3": p["density_g_cm3"], "source": PROVENANCE}


def all_profiles() -> list[dict]:
    return [profile(k) for k in PROFILES]
