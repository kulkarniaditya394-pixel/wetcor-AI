"""Parser and analysis for the project's Arduino corrosion rig (two ACS712 current sensors, two LM393 modules).

The rig compares a "good" and a "corroded" electrode and prints a block of labelled lines to the Serial Monitor:

    Good ACS712 AO: 2.527 V
    Corroded current: 0.153 A
    ...
    RESULT: HEALTHY ELECTRODE

It is a comparative current/voltage rig, not a potentiostat: it does not sweep potential, so no Tafel slopes, R_p or
i_corr exist in its output. What can be calculated honestly is therefore separated here:

* device-reported values and the device's own verdict (origin "measured");
* consistency and resolution checks, which say whether a difference is real or below what the hardware can see;
* a Faraday estimate of the corrosion rate, which is only as good as its stated assumption that the measured current
  is dissolving metal on the stated area;
* a weight-loss rate (ASTM G31 form) when the operator weighed the specimen, which is the defensible number for this rig.
"""
from __future__ import annotations

import math
import re
import statistics

from app.services.electrochemistry import analysis as A

METHOD_VERSION = "rig-1.0.0"
FARADAY = 96485.0  # C/mol e-
SECONDS_PER_DAY = 86400.0
GRAVIMETRIC_K = 8.76e4  # ASTM G31: CR [mm/y] = K W / (A T D), W g, A cm2, T h, D g/cm3
# Datasheet typical values: sensitivity V/A, peak-to-peak output noise V at 2 kHz bandwidth (47 nF filter).
ACS712 = {"ACS712-05B (5 A)": (0.185, 0.021), "ACS712-20A (20 A)": (0.100, 0.011), "ACS712-30A (30 A)": (0.066, 0.007)}
NATURAL_ICORR_REF_UA_CM2 = 1000.0  # far above typical freely corroding steel in saline water (order 1-100 uA/cm2)

_TIMESTAMP = re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*(?:->|-|>)?\s*")
_LINE = re.compile(r"^\s*(?P<label>[^:=]+?)\s*[:=]\s*(?P<value>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*(?P<unit>[a-zA-Zµμ]*)\s*$")
_RESULT = re.compile(r"^\s*(?:result|status|verdict|decision|conclusion)\s*[:=\-]\s*(?P<text>.+?)\s*$", re.I)
_BARE_VERDICT = re.compile(r"^\s*(?:(?:the\s+)?electrode\s+(?:is\s+)?)?(?P<text>(?:not\s+)?(?:healthy|corroded|corroding|damaged)(?:\s+electrode)?)\s*!*\s*$", re.I)

_CORRODED = r"(?:corrod|corros|bad|damag|test\b|sample)"
ROLES: list[tuple[str, re.Pattern]] = [  # order matters: difference lines first, they also contain "current"/"LM"
    ("current_diff_a", re.compile(r"(current.*(diff|delta))|((diff|delta).*current)", re.I)),
    ("lm_diff_signed_v", re.compile(r"sign.*(lm|diff)", re.I)),
    ("lm_diff_abs_v", re.compile(r"abs.*(lm|diff)", re.I)),
    ("good_acs_v", re.compile(r"(good|healthy|ref).*(acs|hall)", re.I)),
    ("corroded_acs_v", re.compile(_CORRODED + r".*(acs|hall)", re.I)),
    ("good_lm_v", re.compile(r"(good|healthy|ref).*(lm\s*-?\s*393|lm\b)", re.I)),
    ("corroded_lm_v", re.compile(_CORRODED + r".*(lm\s*-?\s*393|lm\b)", re.I)),
    ("good_current_a", re.compile(r"(good|healthy|ref).*(current|\bi\b)", re.I)),
    ("corroded_current_a", re.compile(_CORRODED + r".*(current|\bi\b)", re.I)),
]
FIELDS = {
    "good_acs_v": "Good ACS712 AO", "corroded_acs_v": "Corroded ACS712 AO", "good_current_a": "Good current", "corroded_current_a": "Corroded current",
    "current_diff_a": "Current difference", "good_lm_v": "Good LM393 AO", "corroded_lm_v": "Corroded LM393 AO",
    "lm_diff_signed_v": "Signed LM difference", "lm_diff_abs_v": "Absolute LM difference",
}
ESSENTIAL = ("good_current_a", "corroded_current_a")
_SCALE = {"v": 1.0, "mv": 1e-3, "a": 1.0, "ma": 1e-3, "ua": 1e-6, "µa": 1e-6, "μa": 1e-6}


class RigError(ValueError):
    pass


def _verdict(text: str | None) -> str:
    t = (text or "").lower()
    if not t:
        return "unknown"
    negated = bool(re.search(r"\b(not|no|non)\b", t))
    if re.search(r"corrod|corros|damag|fail|bad", t):
        return "healthy" if negated else "corroded"
    if re.search(r"healthy|good|ok\b|pass", t):
        return "corroded" if negated else "healthy"
    return "unknown"


def parse_output(text: str) -> dict:
    """Read pasted Serial Monitor text. Repeated cycles are separated and averaged; nothing unrecognised is dropped silently."""
    if not text or not text.strip():
        raise RigError("Paste the Arduino Serial Monitor output first.")
    blocks: list[dict] = []
    current: dict = {"values": {}, "result": None}
    unrecognised, assumed_units = [], set()

    def close() -> None:
        nonlocal current
        if current["values"] or current["result"]:
            blocks.append(current)
        current = {"values": {}, "result": None}

    for raw in text.splitlines():
        line = _TIMESTAMP.sub("", raw).strip()
        if not line or set(line) <= set("-=*_ "):
            continue
        r = _RESULT.match(line) or _BARE_VERDICT.match(line)
        m = _LINE.match(line)
        if r and not m:
            current["result"] = r.group("text").strip()
            close()
            continue
        if not m:
            unrecognised.append(line[:120])
            continue
        label, value, unit = m.group("label"), float(m.group("value")), m.group("unit")
        role = next((k for k, pat in ROLES if pat.search(label)), None)
        if role is None:
            unrecognised.append(line[:120])
            continue
        if unit:
            scale = _SCALE.get(unit.lower())
            expected = "a" if role.endswith("_a") else "v"
            if scale is None or not unit.lower().endswith(expected):
                raise RigError(f"Unexpected unit '{unit}' in line '{line[:80]}'.")
            value *= scale
        else:
            assumed_units.add(FIELDS[role])
        if role in current["values"]:  # same label again: the next cycle started without a RESULT line
            close()
        current["values"][role] = value
    close()

    blocks = [b for b in blocks if b["values"]]
    if not blocks:
        raise RigError("No rig values found. Expected lines such as 'Good current: 0.145 A' and 'RESULT: HEALTHY ELECTRODE'.")
    warnings: list[str] = []
    complete = [b for b in blocks if all(k in b["values"] for k in ESSENTIAL)]
    if not complete:
        raise RigError("The good and corroded currents are both required ('Good current' and 'Corroded current' lines).")
    if len(complete) < len(blocks):
        warnings.append(f"{len(blocks) - len(complete)} incomplete cycle(s) ignored (usually the first or last when copying).")
    keys = {k for b in complete for k in b["values"]}
    readings = {k: statistics.fmean(b["values"][k] for b in complete if k in b["values"]) for k in keys}
    spread = {k: statistics.stdev(v) for k in keys if len(v := [b["values"][k] for b in complete if k in b["values"]]) > 1}
    results = [b["result"] for b in complete if b["result"]]
    verdicts = [_verdict(t) for t in results]
    counts = {v: verdicts.count(v) for v in sorted(set(verdicts))}
    verdict = max(counts, key=lambda v: counts[v]) if counts else "unknown"
    if len(counts) > 1:
        warnings.append("The device verdict changed between cycles: " + ", ".join(f"{k} {v}x" for k, v in counts.items()) + ".")
    if assumed_units:
        warnings.append(f"No unit printed for: {', '.join(sorted(assumed_units))}. Assumed V for voltages and A for currents.")
    missing = [FIELDS[k] for k in FIELDS if k not in readings]
    return {"n_cycles": len(complete), "readings": readings, "spread": spread, "device_result": results[-1] if results else None, "device_verdict": verdict,
            "verdict_counts": counts, "unrecognised_lines": unrecognised[:20], "missing": missing, "warnings": warnings}


def infer_sensor(readings: dict, vref: float = 5.0) -> dict | None:
    """Which ACS712 variant explains the sketch's AO-to-current conversion? Zero is taken as Vcc/2 (datasheet: ratiometric)."""
    pairs = [(readings.get("good_acs_v"), readings.get("good_current_a")), (readings.get("corroded_acs_v"), readings.get("corroded_current_a"))]
    pairs = [(v, i) for v, i in pairs if v is not None and i is not None]
    if not pairs:
        return None
    zero = vref / 2
    best = None
    for name, (sens, noise) in ACS712.items():
        tol = 0.0005 / sens + 0.0006  # 3-decimal printing of both numbers
        worst = max(abs((v - zero) / sens - i) for v, i in pairs)
        if worst <= tol * 1.5 and (best is None or worst < best["max_error_a"]):
            best = {"variant": name, "sensitivity_v_per_a": sens, "noise_pp_v": noise, "zero_v": zero, "max_error_a": worst}
    return best


def _severity(cr: float) -> str:
    """Qualitative class for carbon steel (NACE SP0775 bands, mm/y)."""
    return "low" if cr < 0.025 else "moderate" if cr <= 0.12 else "high" if cr <= 0.25 else "severe"


def analyze_rig(readings: dict, settings: dict | None = None, *, spread: dict | None = None, n_cycles: int = 1,
                device_result: str | None = None, device_verdict: str | None = None, material: dict | None = None) -> dict:
    s = settings or {}
    spread = spread or {}
    for k in ESSENTIAL:
        if readings.get(k) is None or not math.isfinite(float(readings[k])):
            raise RigError(f"{FIELDS[k]} is required.")
    vref = float(s.get("vref_v") or 5.0)
    bits = int(s.get("adc_bits") or 10)
    lsb_v = vref / (2**bits - 1)
    sensor = infer_sensor(readings, vref)
    sens = float(s.get("sensitivity_v_per_a") or (sensor["sensitivity_v_per_a"] if sensor else 0)) or None
    warnings: list[str] = []
    notes: list[str] = []
    checks: list[dict] = []

    def check(key: str, label: str, value: str, status: str, note: str = "") -> None:
        checks.append({"key": key, "label": label, "value": value, "status": status, "note": note})

    ig, ic = float(readings["good_current_a"]), float(readings["corroded_current_a"])
    zero_g, zero_c = s.get("zero_good_ao_v"), s.get("zero_corroded_ao_v")
    calibrated = zero_g is not None and zero_c is not None and sens and readings.get("good_acs_v") is not None and readings.get("corroded_acs_v") is not None
    if calibrated:
        ig, ic = (float(readings["good_acs_v"]) - float(zero_g)) / sens, (float(readings["corroded_acs_v"]) - float(zero_c)) / sens
        notes.append("Currents recalculated from the AO voltages with your zero-current readings.")
    delta = ic - ig
    if not calibrated and readings.get("current_diff_a") is not None:  # printed from unrounded values, more precise than subtracting 3-decimal prints
        delta = math.copysign(abs(float(readings["current_diff_a"])), delta)
    rel = 100 * delta / ig if ig else None

    # Consistency of what the sketch printed
    if readings.get("current_diff_a") is not None:
        rep = float(readings["current_diff_a"])
        raw = float(readings["corroded_current_a"]) - float(readings["good_current_a"])
        ok = abs(abs(rep) - abs(raw)) <= 0.0016
        check("diff_consistency", "Printed current difference", f"{rep:.3f} A vs {raw:.3f} A recomputed", "pass" if ok else "warn",
              "Agrees within print rounding." if ok else "Does not match Corroded minus Good; check the sketch.")
    if readings.get("lm_diff_signed_v") is not None and readings.get("good_lm_v") is not None and readings.get("corroded_lm_v") is not None:
        raw = float(readings["corroded_lm_v"]) - float(readings["good_lm_v"])
        ok = abs(float(readings["lm_diff_signed_v"]) - raw) <= 0.0016
        check("lm_consistency", "Printed LM difference", f"{float(readings['lm_diff_signed_v']):.3f} V vs {raw:.3f} V recomputed", "pass" if ok else "warn")
    if sensor:
        check("sensor", "Current sensor identified", sensor["variant"], "pass", f"Printed currents match (AO - {sensor['zero_v']:.3f} V) / {sensor['sensitivity_v_per_a'] * 1000:.0f} mV/A.")
    elif readings.get("good_acs_v") is not None:
        check("sensor", "Current sensor identified", "unknown", "warn", "AO voltages do not match a standard ACS712 conversion around Vcc/2; enter the sensitivity to enable resolution checks.")

    # Resolution: what the hardware can actually distinguish
    lsb_a = lsb_v / sens if sens else None
    noise_a = sensor["noise_pp_v"] / sens if sensor and sens else None
    se = None
    if n_cycles >= 3 and "good_current_a" in spread and "corroded_current_a" in spread:
        se = math.sqrt(spread["good_current_a"] ** 2 / n_cycles + spread["corroded_current_a"] ** 2 / n_cycles)
    floor = max(lsb_a or 0, 2 * se if se else 0) or None
    resolved = abs(delta) > floor if floor else None
    if lsb_a:
        check("adc_step", "One ADC step equals", f"{lsb_a * 1000:.1f} mA", "pass" if abs(delta) > lsb_a else "warn",
              f"{bits}-bit ADC at {vref:g} V = {lsb_v * 1000:.2f} mV per count. The current difference is {abs(delta) / lsb_a:.2f} counts.")
    if noise_a:
        check("sensor_noise", "Sensor noise (datasheet typical)", f"about {noise_a * 1000:.0f} mA peak-to-peak", "warn" if abs(delta) < noise_a else "pass",
              "At 2 kHz bandwidth, before any averaging in your sketch.")
    if se is not None:
        check("repeatability", f"Repeatability over {n_cycles} cycles", f"standard error of difference {se * 1000:.2f} mA", "pass" if resolved else "warn")
    elif n_cycles < 3:
        notes.append("Paste 5 or more cycles from the Serial Monitor to measure real repeatability; one cycle cannot show how much the readings fluctuate.")
    if not calibrated and sens:
        notes.append("Two separate ACS712 sensors have different zero offsets, and a few millivolts equal tens of milliamps. Record each AO with no current flowing and enter it below to remove that offset.")

    lm_good, lm_cor = readings.get("good_lm_v"), readings.get("corroded_lm_v")
    if lm_good is not None and lm_cor is not None:
        clipped = max(float(lm_good), float(lm_cor)) >= vref - lsb_v
        lm_delta = float(lm_cor) - float(lm_good)
        check("lm_range", "LM393 reading in range", "at ADC full scale" if clipped else "yes", "warn" if clipped else "pass",
              f"Difference {lm_delta * 1000:+.0f} mV = {abs(lm_delta) / lsb_v:.1f} ADC counts." + (" A channel sits at the 5 V limit, so the true difference could be larger." if clipped else ""))

    # WETCOR's own reading of the comparison, independent of the device threshold
    if resolved is None:
        comparison, comparison_text = "unknown", "Sensor sensitivity unknown, so the size of the difference cannot be judged."
    elif resolved:
        direction = "more" if delta > 0 else "less"
        comparison, comparison_text = "difference", f"The corroded electrode carries {abs(delta) * 1000:.1f} mA {direction} current than the good electrode, which is above what this hardware can resolve ({floor * 1000:.1f} mA)."
    else:
        comparison, comparison_text = "no_difference", f"The {abs(delta) * 1000:.1f} mA difference is smaller than what this hardware can resolve ({floor * 1000:.1f} mA: one ADC step, or the measured scatter), so the two electrodes cannot be told apart by current."
    verdict = device_verdict or _verdict(device_result)
    agreement = None
    if verdict in ("healthy", "corroded") and comparison in ("difference", "no_difference"):
        agreement = (verdict == "healthy") == (comparison == "no_difference")
        if not agreement:
            warnings.append("The device verdict and the resolved current difference disagree. Check the thresholds in the sketch and the LM393 channel.")

    # Quantities that need the operator's inputs
    metrics: list[dict] = []
    area = s.get("exposed_area_cm2")
    mat = material or {}
    ew, rho, src = mat.get("equivalent_weight_g_eq"), mat.get("density_g_cm3"), (mat.get("source") or "").strip()
    needs: list[str] = []
    assumption = ["All of this current dissolves metal from the stated exposed area (it is Faradaic, not leakage, drive current or sensor offset).",
                  "Uniform corrosion over the exposed area.", "Rig currents are steady over the exposure."]
    if not area:
        needs.append("exposed electrode area")
    if ew is None or rho is None:
        needs.append("material")
    elif not src:
        needs.append("source of the material properties")
    faraday = None
    if not needs:
        area = float(area)
        i_ua = abs(ic) / area * 1e6
        metrics.append(A.metric("rig_current_density", "Corroded electrode current density", i_ua, "uA/cm2", "i = I / A", parameters={"current_A": ic, "area_cm2": area}))
        faraday = A.corrosion_rate_mm_per_year(i_ua, ew, rho)
        low, high = None, None
        band = max(lsb_a or 0, noise_a / 2 if noise_a else 0)
        if band:
            low = A.corrosion_rate_mm_per_year(max(abs(ic) - band, 1e-9) / area * 1e6, ew, rho)
            high = A.corrosion_rate_mm_per_year((abs(ic) + band) / area * 1e6, ew, rho)
        plausible = i_ua <= NATURAL_ICORR_REF_UA_CM2
        rate_warn = [] if plausible else [f"{i_ua:,.0f} uA/cm2 is far above the 1 to 100 uA/cm2 typical of steel corroding freely in salt water, so this is a current being driven through the electrode (or a sensor offset), not a natural corrosion current. The figure is an upper bound."]
        metrics.append(A.metric("rig_faraday_rate", "Corrosion rate if all current dissolves metal (Faraday estimate)", faraday, "mm/y", "CR = 0.00327 * (I/A)[uA/cm2] * EW / rho",
                                parameters={"current_A": ic, "area_cm2": area, "equivalent_weight_g_eq": ew, "density_g_cm3": rho, "material_source": src, "range_low_mm_y": low, "range_high_mm_y": high},
                                assumptions=assumption, warnings=rate_warn))
        metrics.append(A.metric("rig_mass_loss_rate", "Metal loss implied by that current", abs(ic) * ew / FARADAY * SECONDS_PER_DAY, "g/day", "m/t = I * EW / F",
                                parameters={"current_A": ic, "equivalent_weight_g_eq": ew}, assumptions=assumption[:1]))
        if delta > 0:
            excess = A.corrosion_rate_mm_per_year(delta / area * 1e6, ew, rho)
            metrics.append(A.metric("rig_excess_rate", "Extra rate from the current difference (Corroded - Good)", excess, "mm/y", "CR = 0.00327 * (dI/A)[uA/cm2] * EW / rho",
                                    parameters={"delta_current_A": delta, "area_cm2": area, "equivalent_weight_g_eq": ew, "density_g_cm3": rho, "material_source": src},
                                    assumptions=assumption, warnings=[] if resolved else ["The current difference is below what the hardware can resolve; treat this as zero."], valid=bool(resolved)))
        warnings.extend(rate_warn)
    gravimetric = None
    m0, m1, hours = s.get("mass_before_g"), s.get("mass_after_g"), s.get("exposure_h")
    if m0 is not None and m1 is not None and hours:
        loss = float(m0) - float(m1)
        if loss < 0:
            warnings.append("Mass after exposure is higher than before: remove corrosion products (ASTM G1 cleaning) and weigh again.")
        elif area and rho is not None and src:
            gravimetric = GRAVIMETRIC_K * loss / (float(area) * float(hours) * float(rho))
            metrics.append(A.metric("rig_gravimetric_rate", "Corrosion rate from weight loss", gravimetric, "mm/y", "CR = 8.76e4 * W / (A * T * D)  (ASTM G31 form)",
                                    parameters={"mass_loss_g": loss, "area_cm2": float(area), "exposure_h": float(hours), "density_g_cm3": rho, "material_source": src},
                                    assumptions=["Corrosion products were removed before the final weighing.", "Uniform corrosion over the exposed area."]))
            if faraday:
                efficiency = 100 * gravimetric / faraday
                metrics.append(A.metric("rig_current_efficiency", "Weight loss vs Faraday estimate", efficiency, "%", "100 * CR(weight loss) / CR(Faraday)",
                                        parameters={"gravimetric_mm_y": gravimetric, "faraday_mm_y": faraday}))
    best = gravimetric if gravimetric is not None else None
    return {
        "method_version": METHOD_VERSION, "device_result": device_result, "device_verdict": verdict, "n_cycles": n_cycles,
        "currents": {"good_a": ig, "corroded_a": ic, "delta_a": delta, "delta_percent": rel, "calibrated": bool(calibrated)},
        "comparison": comparison, "comparison_text": comparison_text, "agrees_with_device": agreement,
        "resolution": {"adc_lsb_v": lsb_v, "adc_step_a": lsb_a, "noise_pp_a": noise_a, "floor_a": floor, "resolved": resolved},
        "sensor": sensor, "checks": checks, "metrics": metrics, "needs": needs, "warnings": warnings, "notes": notes,
        "severity": {"value_mm_y": best, "label": _severity(best), "basis": "weight loss"} if best is not None else None,
    }
