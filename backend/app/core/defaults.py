"""Configurable analysis limits. Every value is a software/quality-control setting, not a physical law.

Stored overrides live in the app_settings table (key "analysis"); each saved result records the
limits that were in force when it was computed.
"""
from __future__ import annotations

import copy
from typing import Any

# key -> (default, description)
SPEC: dict[str, dict[str, tuple[Any, str]]] = {
    "wettability": {
        "primary_method": ("polynomial", "Angle reported as the measurement: 'polynomial' (local tangent, handles asymmetric drops) or 'circle' (spherical-cap fit)."),
        "fit_radius_fraction": (0.2, "Local-tangent fitting region: radius around each contact point as a fraction of the droplet's maximum width."),
        "exclude_px": (3.0, "Boundary points closer than this to the baseline are excluded from fits (blur/corner region); the fit is extrapolated to the baseline."),
        "poly_degree": (2, "Degree of the local polynomial fitted to each side of the profile."),
        "min_contour_points": (40, "Minimum number of droplet boundary points above the baseline required to attempt any fit."),
        "min_side_points": (8, "Minimum boundary points inside each side's fitting region."),
        "max_poly_rms_px": (1.5, "Local-tangent fit is flagged when its RMS residual (px) exceeds this."),
        "circle_max_rel_rms": (0.015, "Spherical-cap fit is rejected when RMS residual / radius exceeds this (drop not a circular cap, e.g. gravity flattening)."),
        "lr_diff_warn_deg": (4.0, "Warn when left and right angles differ by more than this (deg)."),
        "lr_diff_fail_deg": (10.0, "Flag the measurement for correction when left and right differ by more than this (deg)."),
        "method_disagreement_warn_deg": (5.0, "Warn when local-tangent and circle-fit means differ by more than this (deg)."),
        "min_contrast_levels": (25.0, "Warn when droplet/background grey-level separation is below this."),
        "fail_contrast_levels": (10.0, "Refuse automatic detection below this grey-level separation."),
        "clip_fraction_warn": (0.02, "Warn when more than this fraction of pixels is saturated (0 or 255)."),
        "classification_display_tolerance_deg": (2.0, "Display tolerance around 90 deg that triggers a 'repeat measurement' recommendation. A UI setting, not a measurement uncertainty."),
    },
    "electrochemistry": {
        "ocp_drift_warn_mv_per_min": (1.0, "OCP considered not yet stable when |drift| over the selected interval exceeds this (mV/min)."),
        "lpr_default_window_mv": (10.0, "Default half-width of the LPR fitting window around E_corr (mV)."),
        "lpr_max_window_mv": (25.0, "Warn when the LPR half-window exceeds this (linearity assumption weakens)."),
        "lpr_min_r2": (0.99, "Warn when the LPR linear fit R^2 is below this."),
        "lpr_min_points": (5, "Minimum points inside the LPR window."),
        "tafel_min_r2": (0.98, "Tafel branch fit is unreliable below this R^2."),
        "tafel_min_decades": (1.0, "Minimum decades of current spanned by each Tafel region."),
        "tafel_min_points": (8, "Minimum points per Tafel region."),
        "tafel_min_overpotential_mv": (50.0, "Warn when a Tafel region starts closer than this to E_corr (mV)."),
        "tafel_ecorr_mismatch_mv": (20.0, "Warn when the Tafel-intersection E_corr differs from the observed zero-current potential by more than this (mV)."),
        "eis_consistency_tolerance": (0.05, "Warn when supplied |Z| differs from sqrt(Z'^2+Z''^2) by more than this fraction."),
    },
    "ml": {
        "min_groups_exploratory": (4, "Fewer independent specimen groups than this: training is disabled."),
        "min_groups_validated": (15, "At least this many independent groups (and no demo data) before results may carry the 'validated evaluation' badge."),
        "max_folds": (5, "Maximum number of grouped cross-validation folds."),
        "default_seed": (42, "Default random seed."),
    },
}


def defaults() -> dict[str, dict[str, Any]]:
    return {section: {k: v[0] for k, v in items.items()} for section, items in SPEC.items()}


def merge(overrides: dict | None) -> dict[str, dict[str, Any]]:
    """Apply stored overrides onto defaults, ignoring unknown keys and wrong types."""
    out = defaults()
    for section, items in (overrides or {}).items():
        if section not in out or not isinstance(items, dict):
            continue
        for key, value in items.items():
            if key not in out[section]:
                continue
            default = out[section][key]
            if isinstance(default, str):
                if isinstance(value, str):
                    out[section][key] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                out[section][key] = type(default)(value)
    return copy.deepcopy(out)
