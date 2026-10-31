"""Stateless analysis entry points shared by the local API and the in-browser (Pyodide) engine.

Pure functions: bytes and plain dicts in, JSON-safe dicts out. No database, no files, no FastAPI, so the
module (with the wettability and electrochemistry services) also runs unchanged inside the browser, where
the hosted static site uses it to analyse a user's own files without uploading them anywhere.
"""
from __future__ import annotations

import base64
from typing import Any

import numpy as np

from app.core import defaults as D
from app.core.serial import clean
from app.services.electrochemistry import analysis as A
from app.services.electrochemistry import arduino as RIG
from app.services.electrochemistry import materials as MAT
from app.services.electrochemistry.parser import ParseError, parse_table, suggest_mapping
from app.services.electrochemistry.units import CANONICAL, FACTORS, UnitError
from app.services.wettability.detection import analyze as analyze_ca
from app.services.wettability.overlay import render_overlay


class QuickError(Exception):
    """A refusal with an HTTP-like status (422 = input/science refusal)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- wettability

def wettability_analyze(data: bytes, params: dict, limits: dict | None = None, include_auto: bool = True) -> dict:
    lim = limits or D.defaults()["wettability"]
    result = clean(analyze_ca(data, params, lim))
    if include_auto and result.get("manual_correction") and params.get("mode") != "three_point":  # points are nudged often; the page already has the automatic result
        result["auto_result"] = clean(analyze_ca(data, {k: v for k, v in params.items() if k in ("roi", "primary_method")}, lim))
    result["overlay_png_base64"] = base64.b64encode(render_overlay(data, result)).decode() if result["image"] else None
    return result


# ---------------------------------------------------------------- electrochemistry

def corrosion_methods() -> dict:
    return {"methods": A.METHODS, "required": {m: [list(g) for g in r] for m, r in A.REQUIRED.items()},
            "allowed_roles": {m: sorted(r) for m, r in A.ALLOWED.items()}, "units": FACTORS, "canonical": CANONICAL, "materials": MAT.all_profiles()}


def corrosion_preview(data: bytes, filename: str = "") -> dict:
    try:
        t = parse_table(data)
    except ParseError as exc:
        raise QuickError(422, str(exc)) from None
    return clean({
        "filename": filename, "size_bytes": len(data), "encoding": t.encoding, "delimiter": t.delimiter, "decimal_comma": t.decimal_comma,
        "columns": t.columns, "units_row": t.units_row, "n_rows": int(len(t.data)), "header_line": t.header_line, "data_start_line": t.data_start_line,
        "metadata": t.metadata, "warnings": t.warnings, "preview_rows": t.preview_rows(20),
        "raw_head": data[:3000].decode(t.encoding if t.encoding != "utf-8-sig" else "utf-8", errors="replace").splitlines()[:40],
        "suggestion": suggest_mapping(t.columns, t.units_row, t.data),
        "columns_data": {c: t.data[: min(len(t.data), 4000), k] for k, c in enumerate(t.columns)},
    })


def resolve_material(material: dict | None) -> dict | None:
    """Reference profile or user values (with a source). Returns None when no property was supplied."""
    if not material:
        return None
    mat = dict(material)
    if mat.get("profile"):
        if mat["profile"] not in MAT.PROFILES:
            raise QuickError(422, f"Unknown material profile '{mat['profile']}'.")
        mat = {**MAT.profile(mat["profile"]), "is_alloy": False, "profile": mat["profile"]}
    if not any(mat.get(k) is not None for k in ("equivalent_weight_g_eq", "density_g_cm3")):
        return None
    return mat


def rig_parse(text: str) -> dict:
    try:
        return clean(RIG.parse_output(text))
    except RIG.RigError as exc:
        raise QuickError(422, str(exc)) from None


def rig_analyze(body: dict) -> dict:
    """Arduino rig: consistency and resolution checks, verdict comparison, Faraday and weight-loss rates."""
    try:
        return clean(RIG.analyze_rig(body.get("readings") or {}, body.get("settings"), spread=body.get("spread"), n_cycles=int(body.get("n_cycles") or 1),
                                     device_result=body.get("device_result"), device_verdict=body.get("device_verdict"), material=resolve_material(body.get("material"))))
    except (RIG.RigError, A.AnalysisError, TypeError, ValueError) as exc:
        raise QuickError(422, str(exc)) from None


def plot_data(df) -> dict:
    """Canonical-unit columns plus derived plot helpers (same shape as GET /api/corrosion/runs/{id}/data)."""
    out: dict[str, Any] = {c: df[c].tolist() for c in df.columns}
    if "current_density_A_cm2" in df:
        lc = A.log_current(df["current_density_A_cm2"].to_numpy())
        out["log10_abs_current_density"] = lc["log10_abs"]
        out["log_excluded_zero"] = lc["excluded_zero"]
    if "z_real_ohm" in df:
        out["z_mod_calc_ohm"] = np.hypot(df["z_real_ohm"], df["z_imag_ohm"])
        out["phase_calc_deg"] = np.degrees(np.arctan2(df["z_imag_ohm"], df["z_real_ohm"]))
    return out


def corrosion_quick(data: bytes, meta: dict, params: dict | None = None, material: dict | None = None,
                    reference_electrode: str | None = None, limits: dict | None = None) -> dict:
    """Parse + map + analyse a potentiostat export in one call (nothing is stored)."""
    lim = limits or D.defaults()["electrochemistry"]
    method = meta.get("method")
    area = meta.get("exposed_area_cm2")
    try:
        t = parse_table(data)
        df, warnings = A.build_dataset(t, method, meta.get("mapping", {}), meta.get("units", {}), imag_convention=meta.get("imag_convention", "as_is"),
                                       area_cm2=area, anodic_negative=bool(meta.get("anodic_negative")))
        result = A.analyze(method, df, params or {}, lim, area_cm2=area, reference_electrode=reference_electrode, material=resolve_material(material))
    except (ParseError, A.AnalysisError, UnitError, KeyError, TypeError, ValueError) as exc:
        raise QuickError(422, f"Analysis refused: {exc}") from None
    return clean({"method": method, "n_points": len(df), "import_warnings": t.warnings + warnings, "area_cm2": area,
                  "run": {"method": method, "n_points": len(df), "data": plot_data(df)}, "analysis": result})
