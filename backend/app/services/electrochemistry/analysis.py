"""Import normalisation and electrochemical analyses (OCP, LPR, potentiodynamic/Tafel, EIS).

Sign convention after import: anodic current positive (IUPAC); Z = Z' + jZ'' with Z'' stored as
recorded physically (negative for capacitive behaviour). Every derived quantity is returned as a
metric with formula, parameters, assumptions, warnings and a validity flag.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.services.electrochemistry import units as U
from app.services.electrochemistry.parser import ParsedTable

METHOD_VERSION = "ec-1.0.0"
METHODS = {"ocp": "Open-circuit potential", "lpr": "Linear polarisation resistance", "pdp": "Potentiodynamic polarisation", "eis": "Electrochemical impedance spectroscopy"}
REQUIRED: dict[str, list[tuple[str, ...]]] = {
    "ocp": [("time",), ("potential",)],
    "lpr": [("potential",), ("current", "current_density")],
    "pdp": [("potential",), ("current", "current_density")],
    "eis": [("frequency",), ("z_real",), ("z_imag",)],
}
ALLOWED = {"ocp": {"time", "potential"}, "lpr": {"time", "potential", "current", "current_density"},
           "pdp": {"time", "potential", "current", "current_density"}, "eis": {"frequency", "z_real", "z_imag", "z_mod", "phase"}}
CR_CONSTANT = 0.00327  # mm*g/(uA*cm*year), for i in uA/cm2, EW in g/eq, rho in g/cm3


class AnalysisError(ValueError):
    pass


def metric(name: str, label: str, value: float | None, unit: str, formula: str, *, parameters: dict | None = None,
           assumptions: list[str] | None = None, warnings: list[str] | None = None, valid: bool = True) -> dict:
    v = None if value is None or not np.isfinite(value) else float(value)
    return {"name": name, "label": label, "value": v, "unit": unit, "origin": "calculated", "formula": formula,
            "parameters": parameters or {}, "assumptions": assumptions or [], "warnings": warnings or [], "valid": bool(valid and v is not None)}


# ---------------------------------------------------------------- import

def build_dataset(parsed: ParsedTable, method: str, mapping: dict[str, str], units: dict[str, str | None], *,
                  imag_convention: str = "as_is", area_cm2: float | None = None, anodic_negative: bool = False) -> tuple[pd.DataFrame, list[str]]:
    if method not in REQUIRED:
        raise AnalysisError(f"Unknown method '{method}'.")
    mapping = {r: c for r, c in mapping.items() if c}
    extra = set(mapping) - ALLOWED[method]
    if extra:
        raise AnalysisError(f"Roles not used by {METHODS[method]}: {', '.join(sorted(extra))}.")
    for group in REQUIRED[method]:
        if not any(r in mapping for r in group):
            raise AnalysisError(f"{METHODS[method]} requires a column for {' or '.join(g.replace('_', ' ') for g in group)}.")
    warnings: list[str] = []
    out: dict[str, np.ndarray] = {}
    for role, col in mapping.items():
        if col not in parsed.columns:
            raise AnalysisError(f"Column '{col}' is not in the file.")
        quantity = U.ROLE_QUANTITY[role]
        values = U.to_canonical(parsed.data[:, parsed.columns.index(col)], quantity, units.get(role))
        out[U.CANONICAL_COLUMN[role]] = values
    if "z_imag_ohm" in out:
        if imag_convention not in ("as_is", "negated"):
            raise AnalysisError("imag_convention must be 'as_is' (column holds Z'') or 'negated' (column holds -Z'').")
        if imag_convention == "negated":
            out["z_imag_ohm"] = -out["z_imag_ohm"]
    if anodic_negative:
        for key in ("current_A", "current_density_A_cm2"):
            if key in out:
                out[key] = -out[key]
        warnings.append("Current sign inverted on import so that anodic current is positive.")
    if method in ("lpr", "pdp") and "current_density_A_cm2" not in out:
        out["current_density_A_cm2"] = U.current_density(out["current_A"], area_cm2)
        warnings.append(f"Current density calculated as I / A with exposed area {area_cm2:g} cm2.")
    df = pd.DataFrame(out)
    required_cols = [U.CANONICAL_COLUMN[r] for g in REQUIRED[method] for r in g if U.CANONICAL_COLUMN[r] in df]
    before = len(df)
    df = df.dropna(subset=required_cols).reset_index(drop=True)
    if len(df) < before:
        warnings.append(f"{before - len(df)} row(s) with missing required values were excluded.")
    if len(df) < 5:
        raise AnalysisError(f"Only {len(df)} complete data rows; at least 5 are required.")
    if "frequency_Hz" in df and (df["frequency_Hz"] <= 0).any():
        raise AnalysisError("Frequencies must be positive; check the frequency column and unit.")
    if "time_s" in df and (np.diff(df["time_s"]) < 0).any():
        warnings.append("Time values are not monotonically increasing.")
    if "potential_V" in df and df["potential_V"].abs().max() > 5:
        warnings.append("Potentials above 5 V in magnitude: check the potential unit (V vs mV).")
    if "current_A" in df and df["current_A"].abs().max() > 1:
        warnings.append("Currents above 1 A are unusual for a laboratory cell: check the current unit.")
    if "current_density_A_cm2" in df and df["current_density_A_cm2"].abs().max() > 1:
        warnings.append("Current densities above 1 A/cm2: check the current-density unit or area.")
    if "z_real_ohm" in df and (df["z_real_ohm"] < 0).any():
        warnings.append("Negative real impedance values present: check column mapping.")
    dups = int(df.duplicated().sum())
    if dups:
        warnings.append(f"{dups} duplicated data row(s).")
    return df, warnings


# ---------------------------------------------------------------- helpers

def zero_crossing_potential(e: np.ndarray, i: np.ndarray) -> tuple[float, str]:
    """Potential of zero net current: linear interpolation at the first sign change, else |i| minimum."""
    order = np.argsort(e)
    e, i = e[order], i[order]
    sign = np.sign(i)
    idx = np.where(sign[:-1] * sign[1:] < 0)[0]
    exact = np.where(i == 0)[0]
    if exact.size:
        return float(e[exact[0]]), "zero current sample"
    if idx.size:
        k = idx[np.argmin(np.abs(i[idx]))]
        return float(e[k] - i[k] * (e[k + 1] - e[k]) / (i[k + 1] - i[k])), "interpolated zero crossing"
    return float(e[np.argmin(np.abs(i))]), "minimum |i| (no sign change in data)"


def log_current(i: np.ndarray) -> dict:
    """log10|i| for semi-log plots; zero currents excluded explicitly, sign preserved separately."""
    i = np.asarray(i, dtype=float)
    nonzero = (i != 0) & np.isfinite(i)
    out = np.full(i.shape, np.nan)
    out[nonzero] = np.log10(np.abs(i[nonzero]))
    return {"log10_abs": out, "sign": np.sign(i), "excluded_zero": int((~nonzero).sum())}


def _linfit(x: np.ndarray, y: np.ndarray) -> dict:
    res = stats.linregress(x, y)
    return {"slope": float(res.slope), "intercept": float(res.intercept), "r2": float(res.rvalue ** 2), "n": int(len(x)),
            "stderr_slope": float(res.stderr)}


def stern_geary_from_tafel(beta_a: float, beta_c: float) -> float:
    """B = beta_a * beta_c / (2.303 (beta_a + beta_c)); slopes in V/decade (positive magnitudes)."""
    if beta_a <= 0 or beta_c <= 0:
        raise AnalysisError("Tafel slopes must be positive magnitudes (V/decade).")
    return beta_a * beta_c / (np.log(10) * (beta_a + beta_c))


def corrosion_rate_mm_per_year(icorr_ua_cm2: float, ew_g_eq: float | None, density_g_cm3: float | None) -> float:
    """CR [mm/y] = 0.00327 * i_corr [uA/cm2] * EW [g/eq] / rho [g/cm3]."""
    if ew_g_eq is None:
        raise AnalysisError("Equivalent weight is required for a corrosion-rate calculation.")
    if density_g_cm3 is None:
        raise AnalysisError("Material density is required for a corrosion-rate calculation.")
    if icorr_ua_cm2 is None or not np.isfinite(icorr_ua_cm2) or icorr_ua_cm2 <= 0:
        raise AnalysisError("A positive, valid corrosion current density is required.")
    if ew_g_eq <= 0 or density_g_cm3 <= 0:
        raise AnalysisError("Equivalent weight and density must be positive.")
    return CR_CONSTANT * icorr_ua_cm2 * ew_g_eq / density_g_cm3


def _corrosion_rate_metric(icorr: dict, material: dict | None, notes: list[str]) -> dict | None:
    if not material:
        notes.append("Corrosion rate not calculated: no material equivalent weight and density supplied.")
        return None
    ew, rho, src = material.get("equivalent_weight_g_eq"), material.get("density_g_cm3"), (material.get("source") or "").strip()
    if not src:
        notes.append("Corrosion rate not calculated: the source of the material properties must be recorded.")
        return None
    try:
        cr = corrosion_rate_mm_per_year(icorr["value"], ew, rho)
    except AnalysisError as exc:
        notes.append(f"Corrosion rate not calculated: {exc}")
        return None
    w = list(icorr["warnings"])
    if material.get("is_alloy"):
        w.append("Alloy: the equivalent weight depends on composition and assumed valences; confirm the EW method used.")
    return metric("corrosion_rate", "Corrosion penetration rate", cr, "mm/y", "CR = 0.00327 * i_corr[uA/cm2] * EW / rho",
                  parameters={"i_corr_uA_cm2": icorr["value"], "equivalent_weight_g_eq": ew, "density_g_cm3": rho, "material_source": src,
                              "i_corr_source": icorr["name"]},
                  assumptions=["Uniform corrosion over the exposed area.", "Faradaic dissolution of the metal with the stated equivalent weight.",
                               "i_corr from the selected electrochemical analysis is representative of the exposure period."],
                  warnings=w, valid=icorr["valid"])


# ---------------------------------------------------------------- OCP

def analyze_ocp(df: pd.DataFrame, params: dict, lim: dict, reference_electrode: str | None) -> dict:
    t, e = df["time_s"].to_numpy(), df["potential_V"].to_numpy()
    duration = float(t.max() - t.min())
    t0 = params.get("t_start_s")
    t1 = params.get("t_end_s")
    default_interval = t0 is None and t1 is None
    if default_interval:
        t0, t1 = t.max() - 0.2 * duration, t.max()
    sel = (t >= t0) & (t <= t1)
    if sel.sum() < 3:
        raise AnalysisError("Fewer than 3 points in the selected OCP interval.")
    fit = _linfit(t[sel], e[sel])
    drift = fit["slope"] * 1000 * 60  # mV/min
    warnings, notes = [], ["Corrosion current density and corrosion rate cannot be calculated from OCP data alone."]
    if default_interval:
        notes.append("Interval defaulted to the final 20% of the record; select an interval to override.")
    if abs(drift) > lim["ocp_drift_warn_mv_per_min"]:
        warnings.append(f"OCP drift {drift:.2f} mV/min exceeds {lim['ocp_drift_warn_mv_per_min']:g} mV/min: potential not yet stable.")
    ref = reference_electrode or "unspecified reference"
    if not reference_electrode:
        warnings.append("Reference electrode not recorded; potentials cannot be compared between runs.")
    interval = {"t_start_s": float(t0), "t_end_s": float(t1), "n": int(sel.sum())}
    metrics = [
        metric("ocp_mean", f"Mean OCP vs {ref}", e[sel].mean(), "V", "mean(E) over interval", parameters=interval),
        metric("ocp_std", "OCP standard deviation", e[sel].std(ddof=1) * 1000, "mV", "sample std(E) over interval", parameters=interval),
        metric("ocp_drift", "OCP drift", drift, "mV/min", "slope of least-squares line E(t) over interval", parameters={**interval, "r2": fit["r2"]}),
        metric("ocp_final", f"Final recorded OCP vs {ref}", e[-1], "V", "last recorded sample"),
        metric("ocp_duration", "Record duration", duration, "s", "t_max - t_min"),
    ]
    status = "limited" if warnings else "ok"
    return {"status": status, "metrics": metrics, "warnings": warnings, "notes": notes, "fit": {"interval": interval, "drift_line": fit}}


# ---------------------------------------------------------------- LPR

def analyze_lpr(df: pd.DataFrame, params: dict, lim: dict, material: dict | None = None) -> dict:
    e, i = df["potential_V"].to_numpy(), df["current_density_A_cm2"].to_numpy()
    warnings, notes = [], []
    if params.get("e_corr_V") is not None:
        e_corr, how = float(params["e_corr_V"]), "user supplied"
    else:
        e_corr, how = zero_crossing_potential(e, i)
    if params.get("e_low_V") is not None and params.get("e_high_V") is not None:
        lo, hi = float(params["e_low_V"]), float(params["e_high_V"])
        selection = "user_selected"
    else:
        half = float(params.get("half_window_mV") or lim["lpr_default_window_mv"]) / 1000
        lo, hi = e_corr - half, e_corr + half
        selection = "user_selected" if params.get("half_window_mV") else "default_window"
    if not lo < e_corr < hi:
        warnings.append("Fitting window does not contain E_corr; LPR assumes a fit around the corrosion potential.")
    half_mv = max(hi - e_corr, e_corr - lo) * 1000
    if half_mv > lim["lpr_max_window_mv"]:
        warnings.append(f"Window extends {half_mv:.0f} mV from E_corr (> {lim['lpr_max_window_mv']:g} mV): linear approximation may not hold.")
    sel = (e >= lo) & (e <= hi)
    if sel.sum() < lim["lpr_min_points"]:
        raise AnalysisError(f"Only {int(sel.sum())} points inside the LPR window (minimum {lim['lpr_min_points']}). Widen the window or check E_corr.")
    fit = _linfit(i[sel], e[sel])  # E = Rp * i + c
    rp = fit["slope"]
    valid = rp > 0 and fit["r2"] >= lim["lpr_min_r2"]
    if rp <= 0:
        warnings.append("Non-positive slope dE/di: check current sign convention and the selected window.")
    if fit["r2"] < lim["lpr_min_r2"]:
        warnings.append(f"Linear fit R^2 = {fit['r2']:.4f} is below {lim['lpr_min_r2']:g}: data are not linear in this window.")
    window = {"e_low_V": lo, "e_high_V": hi, "e_corr_V": e_corr, "e_corr_method": how, "selection": selection, "n": fit["n"], "r2": fit["r2"]}
    metrics = [
        metric("e_corr_zero_current", "Zero-current potential (E_corr)", e_corr, "V", how),
        metric("rp", "Polarisation resistance R_p", rp, "ohm*cm2", "R_p = (dE/di) at E ~ E_corr (least-squares slope)",
               parameters=window, assumptions=["Current density uses the recorded exposed area.", "Window is small enough for linear behaviour."],
               warnings=list(warnings), valid=valid),
    ]
    b, b_src = params.get("stern_geary_B_V"), (params.get("B_source") or "").strip()
    if b is None and params.get("beta_a_V_dec") and params.get("beta_c_V_dec"):
        b = stern_geary_from_tafel(float(params["beta_a_V_dec"]), float(params["beta_c_V_dec"]))
        b_src = b_src or "computed from user-supplied Tafel slopes"
    if b is not None and b_src and rp > 0:
        icorr = float(b) / rp * 1e6
        m = metric("i_corr", "Corrosion current density i_corr (from LPR)", icorr, "uA/cm2", "i_corr = B / R_p",
                   parameters={"B_V": float(b), "B_source": b_src, "rp_ohm_cm2": rp, "beta_a_V_dec": params.get("beta_a_V_dec"), "beta_c_V_dec": params.get("beta_c_V_dec")},
                   assumptions=["Stern-Geary relation applies (activation control near E_corr)."], warnings=list(warnings), valid=valid)
        metrics.append(m)
        if cr := _corrosion_rate_metric(m, material, notes):
            metrics.append(cr)
    elif b is not None and not b_src:
        notes.append("i_corr not calculated: the source of the Stern-Geary coefficient B must be recorded.")
    else:
        notes.append("i_corr not calculated: no documented Stern-Geary coefficient B (or Tafel slopes) supplied. R_p is reported on its own.")
    fit_line = {"i": [float(i[sel].min()), float(i[sel].max())], "e": [rp * float(i[sel].min()) + fit["intercept"], rp * float(i[sel].max()) + fit["intercept"]]}
    return {"status": "ok" if valid and not warnings else "limited" if valid else "invalid", "metrics": metrics, "warnings": warnings,
            "notes": notes, "fit": {"window": window, "line": fit_line, "fit": fit}}


# ---------------------------------------------------------------- Tafel

def _branch_points(eta: np.ndarray, i: np.ndarray, lo_mv: float, hi_mv: float, branch: str) -> np.ndarray:
    if branch == "anodic":
        return (eta >= lo_mv / 1000) & (eta <= hi_mv / 1000) & (i > 0)
    return (eta <= -lo_mv / 1000) & (eta >= -hi_mv / 1000) & (i < 0)


def _fit_branch(e, logi, eta, i, lo, hi, branch, lim) -> dict:
    sel = _branch_points(eta, i, lo, hi, branch)
    n = int(sel.sum())
    out: dict[str, Any] = {"range_mV": [lo, hi], "n": n, "problems": []}
    if n < 3:
        out["problems"].append(f"{n} points in the {branch} region.")
        return out
    fit = _linfit(logi[sel], e[sel])  # E = a + b log|i|
    decades = float(np.ptp(logi[sel]))
    out.update(fit=fit, decades=decades, slope_V_dec=fit["slope"], r2=fit["r2"], log_i_range=[float(logi[sel].min()), float(logi[sel].max())])
    expected = fit["slope"] > 0 if branch == "anodic" else fit["slope"] < 0
    if not expected:
        out["problems"].append(f"{branch} slope has the wrong sign (check current sign convention).")
    if n < lim["tafel_min_points"]:
        out["problems"].append(f"{n} points (< {lim['tafel_min_points']}).")
    if fit["r2"] < lim["tafel_min_r2"]:
        out["problems"].append(f"R^2 {fit['r2']:.4f} < {lim['tafel_min_r2']:g}.")
    if decades < lim["tafel_min_decades"]:
        out["problems"].append(f"spans {decades:.2f} decades of current (< {lim['tafel_min_decades']:g}).")
    return out


def propose_tafel_regions(e, logi, eta, i, lim) -> dict:
    """Search candidate overpotential windows per branch; propose the best-R^2 window that meets the criteria."""
    proposal = {}
    for branch in ("anodic", "cathodic"):
        best = None
        for start in range(int(lim["tafel_min_overpotential_mv"]), 201, 10):
            for width in (50, 75, 100, 150, 200):
                b = _fit_branch(e, logi, eta, i, start, start + width, branch, lim)
                if b["problems"]:
                    continue
                key = (round(b["r2"], 3), b["decades"])
                if best is None or key > best[0]:
                    best = (key, [start, start + width])
        proposal[branch] = best[1] if best else None
    return proposal


def analyze_tafel(df: pd.DataFrame, params: dict, lim: dict, material: dict | None = None) -> dict:
    e, i = df["potential_V"].to_numpy(), df["current_density_A_cm2"].to_numpy()
    lc = log_current(i)
    logi = lc["log10_abs"]
    keep = np.isfinite(logi)
    e_corr_obs, how = zero_crossing_potential(e, i)
    eta = e - e_corr_obs
    warnings, notes = [], []
    if lc["excluded_zero"]:
        notes.append(f"{lc['excluded_zero']} zero-current point(s) excluded from log|i| (logarithm undefined); original values preserved.")
    proposal = propose_tafel_regions(e[keep], logi[keep], eta[keep], i[keep], lim)
    if params.get("anodic_mV") and params.get("cathodic_mV"):
        regions, selection = {"anodic": list(params["anodic_mV"]), "cathodic": list(params["cathodic_mV"])}, "user_selected"
    else:
        regions, selection = proposal, "auto_proposed"
    result: dict[str, Any] = {"metrics": [metric("e_corr_zero_current", "Zero-current potential (observed)", e_corr_obs, "V", how)],
                              "warnings": warnings, "notes": notes,
                              "fit": {"selection": selection, "proposal": proposal, "regions": regions, "e_corr_obs_V": e_corr_obs}}
    if regions.get("anodic") is None or regions.get("cathodic") is None:
        missing = [b for b in ("anodic", "cathodic") if regions.get(b) is None]
        warnings.append(f"No suitable linear Tafel region found automatically for: {', '.join(missing)}. Select regions manually or treat the curve as unsuitable for Tafel extrapolation.")
        result["status"] = "invalid"
        return result
    branches = {b: _fit_branch(e[keep], logi[keep], eta[keep], i[keep], *regions[b], b, lim) for b in ("anodic", "cathodic")}
    result["fit"]["branches"] = branches
    problems = [f"{b}: {p}" for b, br in branches.items() for p in br["problems"]]
    if any("fit" not in br for br in branches.values()):
        warnings.extend(problems)
        result["status"] = "invalid"
        return result
    for b, br in branches.items():
        if br["range_mV"][0] < lim["tafel_min_overpotential_mv"]:
            warnings.append(f"{b} region starts {br['range_mV'][0]:g} mV from E_corr (< {lim['tafel_min_overpotential_mv']:g} mV): mixed control likely.")
    ba, bc = branches["anodic"]["fit"], branches["cathodic"]["fit"]
    if abs(ba["slope"] - bc["slope"]) < 1e-12:
        raise AnalysisError("Tafel lines are parallel; no intersection.")
    x = (bc["intercept"] - ba["intercept"]) / (ba["slope"] - bc["slope"])
    e_corr_fit = ba["intercept"] + ba["slope"] * x
    icorr_A = 10 ** x
    beta_a, beta_c = ba["slope"], -bc["slope"]
    mismatch = abs(e_corr_fit - e_corr_obs) * 1000
    if mismatch > lim["tafel_ecorr_mismatch_mv"]:
        warnings.append(f"Tafel intersection E_corr differs from the observed zero-current potential by {mismatch:.1f} mV.")
    for name, beta in (("beta_a", beta_a), ("beta_c", beta_c)):
        if beta > 0 and not 0.02 <= beta <= 0.4:
            warnings.append(f"{name} = {beta * 1000:.0f} mV/dec lies outside 20-400 mV/dec (heuristic plausibility range); region may not be activation controlled.")
    if selection == "auto_proposed":
        warnings.append("Fit regions were proposed automatically. Review them and confirm (user-selected) before relying on the result.")
    valid = not problems
    warnings.extend(problems)
    params_rec = {"anodic_mV": regions["anodic"], "cathodic_mV": regions["cathodic"], "selection": selection,
                  "anodic_r2": ba["r2"], "cathodic_r2": bc["r2"], "anodic_decades": branches["anodic"]["decades"], "cathodic_decades": branches["cathodic"]["decades"]}
    common = dict(parameters=params_rec, assumptions=["Both regions are activation controlled (linear in E vs log|i|).",
                                                       "Current density uses the recorded exposed area.", "Ohmic drop negligible or compensated."],
                  warnings=list(warnings), valid=valid)
    icorr = metric("i_corr", "Corrosion current density i_corr (Tafel extrapolation)", icorr_A * 1e6, "uA/cm2",
                   "log10 i_corr at the intersection of anodic and cathodic Tafel lines", **common)
    result["metrics"] += [
        icorr,
        metric("e_corr_tafel", "E_corr at Tafel intersection", e_corr_fit, "V", "E at intersection of Tafel lines", **common),
        metric("beta_a", "Anodic Tafel slope beta_a", beta_a * 1000, "mV/dec", "dE/dlog10|i| over anodic region", **common),
        metric("beta_c", "Cathodic Tafel slope beta_c", beta_c * 1000, "mV/dec", "-dE/dlog10|i| over cathodic region", **common),
    ]
    if beta_a > 0 and beta_c > 0:
        result["metrics"].append(metric("stern_geary_B", "Stern-Geary coefficient B", stern_geary_from_tafel(beta_a, beta_c) * 1000, "mV",
                                        "B = beta_a*beta_c / (2.303 (beta_a + beta_c))", **common))
    if cr := _corrosion_rate_metric(icorr, material, notes):
        result["metrics"].append(cr)
    result["fit"]["lines"] = {b: {"slope_V_dec": br["fit"]["slope"], "intercept_V": br["fit"]["intercept"], "log_i_range": br["log_i_range"]} for b, br in branches.items()}
    result["fit"]["intersection"] = {"log10_i": x, "e_V": e_corr_fit}
    result["status"] = "invalid" if not valid else "limited" if selection == "auto_proposed" or warnings else "ok"
    return result


# ---------------------------------------------------------------- EIS

def analyze_eis(df: pd.DataFrame, params: dict, lim: dict, area_cm2: float | None) -> dict:
    f, zr, zi = df["frequency_Hz"].to_numpy(), df["z_real_ohm"].to_numpy(), df["z_imag_ohm"].to_numpy()
    warnings, notes = [], ["No corrosion rate is derived from EIS without a validated equivalent-circuit model and a documented Stern-Geary coefficient."]
    zmod, phase = np.hypot(zr, zi), np.degrees(np.arctan2(zi, zr))
    if "z_mod_ohm" in df:
        rel = np.abs(df["z_mod_ohm"].to_numpy() - zmod) / np.maximum(zmod, 1e-30)
        if np.nanmax(rel) > lim["eis_consistency_tolerance"]:
            warnings.append(f"Supplied |Z| differs from sqrt(Z'^2+Z''^2) by up to {np.nanmax(rel) * 100:.1f}%: check column mapping/units.")
    if "phase_deg" in df:
        dphi = np.abs(((df["phase_deg"].to_numpy() - phase) + 180) % 360 - 180)
        if np.nanmax(dphi) > 2 and np.nanmax(np.abs(np.abs(df["phase_deg"].to_numpy()) - np.abs(phase))) <= 2:
            notes.append("Supplied phase uses the opposite sign convention (-phase); computed phase is used.")
        elif np.nanmax(dphi) > 2:
            warnings.append("Supplied phase disagrees with atan2(Z'', Z') by more than 2 deg: check imaginary-part sign convention.")
    if len(np.unique(f)) < len(f):
        warnings.append("Duplicated frequencies present.")
    d = np.diff(f)
    if not ((d < 0).all() or (d > 0).all()):
        warnings.append("Frequencies are not monotonic (possible repeated sweep or drift).")
    lo, hi = int(np.argmin(f)), int(np.argmax(f))
    if zi[lo] > 0:
        notes.append("Positive Z'' at the lowest frequency (inductive behaviour or instability).")
    span = float(np.log10(f.max() / f.min()))
    metrics = [
        metric("z_mod_low_f", f"|Z| at lowest frequency ({f[lo]:.3g} Hz)", zmod[lo], "ohm", "sqrt(Z'^2 + Z''^2) at f_min", parameters={"frequency_Hz": float(f[lo])}),
        metric("z_real_high_f", f"Z' at highest frequency ({f[hi]:.3g} Hz)", zr[hi], "ohm", "Z' at f_max",
               assumptions=["Approximates solution resistance only if the high-frequency limit was reached."], parameters={"frequency_Hz": float(f[hi])}),
        metric("eis_decades", "Frequency span", span, "decades", "log10(f_max / f_min)"),
    ]
    if area_cm2:
        metrics.append(metric("z_mod_low_f_area", "|Z| at lowest frequency, area-normalised", zmod[lo] * area_cm2, "ohm*cm2", "|Z|(f_min) * A",
                              parameters={"area_cm2": area_cm2}))
    return {"status": "limited" if warnings else "ok", "metrics": metrics, "warnings": warnings, "notes": notes,
            "fit": {"computed": {"z_mod_ohm": zmod.tolist(), "phase_deg": phase.tolist()}}}


def analyze(method: str, df: pd.DataFrame, params: dict, lim: dict, *, area_cm2: float | None = None,
            reference_electrode: str | None = None, material: dict | None = None) -> dict:
    if method == "ocp":
        out = analyze_ocp(df, params, lim, reference_electrode)
        if material:
            out["warnings"].append("Material properties were supplied, but a corrosion rate cannot be derived from OCP data.")
    elif method == "lpr":
        out = analyze_lpr(df, params, lim, material)
    elif method == "pdp":
        out = analyze_tafel(df, params, lim, material)
    elif method == "eis":
        out = analyze_eis(df, params, lim, area_cm2)
    else:
        raise AnalysisError(f"Unknown method '{method}'.")
    out.update(method=method, method_version=METHOD_VERSION, params=params, limits=lim)
    return out
