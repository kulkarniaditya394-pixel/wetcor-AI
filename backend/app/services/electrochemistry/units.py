"""Explicit unit handling. Unknown or missing units raise UnitError; nothing is assumed silently."""
from __future__ import annotations

import math
import re

import numpy as np

FACTORS: dict[str, dict[str, float]] = {
    "time": {"s": 1.0, "ms": 1e-3, "min": 60.0, "h": 3600.0},
    "potential": {"V": 1.0, "mV": 1e-3},
    "current": {"A": 1.0, "mA": 1e-3, "uA": 1e-6, "nA": 1e-9, "pA": 1e-12},
    "current_density": {"A/cm2": 1.0, "mA/cm2": 1e-3, "uA/cm2": 1e-6, "nA/cm2": 1e-9, "A/m2": 1e-4, "mA/m2": 1e-7},
    "area": {"cm2": 1.0, "mm2": 1e-2, "m2": 1e4},
    "frequency": {"Hz": 1.0, "mHz": 1e-3, "kHz": 1e3, "MHz": 1e6},
    "impedance": {"ohm": 1.0, "mohm": 1e-3, "kohm": 1e3, "Mohm": 1e6},
    "phase": {"deg": 1.0, "rad": 180.0 / math.pi},
}
CANONICAL = {"time": "s", "potential": "V", "current": "A", "current_density": "A/cm2", "area": "cm2",
             "frequency": "Hz", "impedance": "ohm", "phase": "deg"}
ROLE_QUANTITY = {"time": "time", "potential": "potential", "current": "current", "current_density": "current_density",
                 "frequency": "frequency", "z_real": "impedance", "z_imag": "impedance", "z_mod": "impedance", "phase": "phase"}
CANONICAL_COLUMN = {"time": "time_s", "potential": "potential_V", "current": "current_A", "current_density": "current_density_A_cm2",
                    "frequency": "frequency_Hz", "z_real": "z_real_ohm", "z_imag": "z_imag_ohm", "z_mod": "z_mod_ohm", "phase": "phase_deg"}


class UnitError(ValueError):
    pass


_ALIASES = {  # lower-case spelling -> canonical (only where case cannot change the meaning)
    "s": "s", "sec": "s", "secs": "s", "second": "s", "seconds": "s", "ms": "ms", "msec": "ms",
    "min": "min", "minute": "min", "minutes": "min", "h": "h", "hr": "h", "hour": "h", "hours": "h",
    "v": "V", "volt": "V", "volts": "V", "mv": "mV",
    "a": "A", "amp": "A", "amps": "A", "ma": "mA", "ua": "uA", "na": "nA", "pa": "pA",
    "deg": "deg", "degree": "deg", "degrees": "deg", "rad": "rad", "radian": "rad", "radians": "rad",
    "cm2": "cm2", "mm2": "mm2", "m2": "m2",
}
_SI_PREFIX = {"": "", "k": "k", "K": "k", "m": "m", "M": "M"}


def normalize_unit(raw: str | None) -> str | None:
    """Map common spellings ('µA', 'Ω', 'cm²', 'kOhm', 'A cm-2', 'V vs. SCE') to canonical keys; None if unknown.

    Prefix case is respected where it matters (mHz vs MHz, mOhm vs MOhm).
    """
    if not raw:
        return None
    u = raw.strip().strip("()[]{} ")
    u = u.replace("μ", "u").replace("µ", "u").replace("Ω", "ohm").replace("Ω", "ohm").replace("°", "deg")
    u = u.replace("²", "2").replace("^2", "2").replace("·", "").replace(" ", "")
    u = re.sub(r"(?i)vs\.?.*$", "", u)
    u = re.sub(r"(?i)cm-2$", "/cm2", u)
    u = re.sub(r"(?i)(?<!c)m-2$", "/m2", u)
    if not u:
        return None
    if u.lower().endswith("ohm"):
        pre = u[:-3]
        return {"": "ohm", "k": "kohm", "M": "Mohm", "m": "mohm"}.get(_SI_PREFIX.get(pre, "?"))
    if u.lower().endswith("hz"):
        pre = u[:-2]
        return {"": "Hz", "k": "kHz", "M": "MHz", "m": "mHz"}.get(_SI_PREFIX.get(pre, "?"))
    if "/" in u:
        num, den = u.split("/", 1)
        cand = f"{_ALIASES.get(num.lower(), num)}/{den.lower()}"
        return cand if cand in FACTORS["current_density"] else None
    return _ALIASES.get(u.lower())


def factor(quantity: str, unit: str) -> float:
    try:
        return FACTORS[quantity][unit]
    except KeyError:
        raise UnitError(f"Unit '{unit}' is not valid for {quantity.replace('_', ' ')}. Allowed: {', '.join(FACTORS.get(quantity, {}))}") from None


def to_canonical(values, quantity: str, unit: str | None):
    if not unit:
        raise UnitError(f"No unit selected for {quantity.replace('_', ' ')}.")
    return np.asarray(values, dtype=float) * factor(quantity, unit)


def convert(value: float, quantity: str, from_unit: str, to_unit: str) -> float:
    return value * factor(quantity, from_unit) / factor(quantity, to_unit)


def current_density(current_a, area_cm2: float | None):
    """i = I / A  [A/cm2]."""
    if area_cm2 is None or not np.isfinite(area_cm2) or area_cm2 <= 0:
        raise UnitError("A positive exposed electrode area is required to convert current into current density.")
    return np.asarray(current_a, dtype=float) / area_cm2
