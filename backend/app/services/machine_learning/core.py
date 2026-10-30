"""Dataset readiness, grouped evaluation and model persistence for the contact-angle research question.

Question: does adding contact angle to material/test metadata reduce out-of-group prediction error
of an electrochemical response? Every configuration is evaluated on identical specimen-grouped
folds; preprocessing lives inside scikit-learn pipelines so it is fitted on training folds only.
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGETS: dict[str, dict[str, str]] = {
    "i_corr": {"label": "Corrosion current density i_corr", "unit": "uA/cm2", "metric": "i_corr",
               "explain": "Calculated from Tafel extrapolation (user-confirmed regions) or LPR with a documented Stern-Geary B."},
    "corrosion_rate": {"label": "Corrosion penetration rate", "unit": "mm/y", "metric": "corrosion_rate",
                       "explain": "Calculated from a valid i_corr with recorded equivalent weight and density."},
    "rp": {"label": "Polarisation resistance R_p", "unit": "ohm*cm2", "metric": "rp", "explain": "Calculated from the LPR slope dE/di near E_corr."},
}
FEATURES: dict[str, tuple[str, str]] = {
    "material": ("categorical", "Specimen material"),
    "surface_preparation": ("categorical", "Surface preparation / treatment"),
    "electrolyte": ("categorical", "Electrolyte"),
    "concentration_value": ("numeric", "Electrolyte concentration (single recorded unit)"),
    "temperature_c": ("numeric", "Test temperature (C)"),
    "roughness_ra_um": ("numeric", "Surface roughness Ra (um)"),
    "contact_angle_deg": ("numeric", "Mean water contact angle (deg)"),
}
WETTABILITY_FEATURE = "contact_angle_deg"
# Electrochemical outputs that would leak the target if used as inputs.
LEAKY = {"i_corr", "corrosion_rate", "rp", "beta_a", "beta_c", "stern_geary_B", "e_corr_tafel", "e_corr_zero_current",
         "target", "target_value", "z_mod_low_f", "ocp_mean"}
CONFIGS = [
    ("Mean-only baseline", "mean", "none"),
    ("Linear regression - baseline", "linear", "baseline"),
    ("Linear regression + contact angle", "linear", "wettability"),
    ("Random forest - baseline", "random_forest", "baseline"),
    ("Random forest + contact angle", "random_forest", "wettability"),
]


class MLError(ValueError):
    pass


def validate_request(target: str, features: list[str], transform: str) -> None:
    if target not in TARGETS:
        raise MLError(f"Unknown target '{target}'. Valid targets: {', '.join(TARGETS)}.")
    leak = [f for f in features if f in LEAKY or f == target]
    if leak:
        raise MLError(f"Target leakage: {', '.join(leak)} are electrochemical outputs and cannot be model inputs.")
    unknown = [f for f in features if f not in FEATURES]
    if unknown:
        raise MLError(f"Features not permitted: {', '.join(unknown)}.")
    if WETTABILITY_FEATURE in features:
        raise MLError("List baseline features only; the contact-angle feature is added automatically to the wettability configuration.")
    if transform not in ("none", "log10"):
        raise MLError("target_transform must be 'none' or 'log10'.")


def dataset_hash(rows: list[dict], target: str, features: list[str]) -> str:
    payload = json.dumps({"target": target, "features": features, "rows": sorted(rows, key=lambda r: r["run_id"])}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def readiness(rows: list[dict], target: str, features: list[str], policy: dict, excluded: list[dict] | None = None) -> dict:
    df = pd.DataFrame(rows)
    n = len(df)
    groups = int(df["specimen_code"].nunique()) if n else 0
    blocking, advisories = [], []
    report: dict[str, Any] = {"target": target, "target_unit": TARGETS[target]["unit"], "n_records": n, "n_groups": groups,
                              "excluded": excluded or [], "features": {}, "demo_records": int(df["is_demo"].sum()) if n else 0}
    if n == 0:
        blocking.append(f"No records with a valid '{TARGETS[target]['label']}' result.")
    else:
        y = df["target"].astype(float)
        report["target_stats"] = {"mean": float(y.mean()), "std": float(y.std(ddof=1)) if n > 1 else None,
                                  "min": float(y.min()), "max": float(y.max())}
        if n > 1 and float(y.std(ddof=1)) == 0:
            blocking.append("Target has no variation; nothing to predict.")
        for f in features + [WETTABILITY_FEATURE]:
            col = df[f] if f in df else pd.Series([None] * n)
            missing = int(col.isna().sum())
            info: dict[str, Any] = {"kind": FEATURES[f][0], "missing": missing, "missing_fraction": missing / n}
            if FEATURES[f][0] == "categorical":
                info["categories"] = {str(k): int(v) for k, v in col.dropna().value_counts().items()}
            else:
                vals = pd.to_numeric(col, errors="coerce").dropna()
                info.update(min=float(vals.min()) if len(vals) else None, max=float(vals.max()) if len(vals) else None,
                            std=float(vals.std(ddof=1)) if len(vals) > 1 else None)
            report["features"][f] = info
            if missing == n:
                advisories.append(f"Feature '{f}' is never recorded and will be ignored.")
            elif missing:
                advisories.append(f"Feature '{f}' is missing in {missing}/{n} records (median/constant imputation inside each training fold).")
        ca = report["features"][WETTABILITY_FEATURE]
        if ca["missing"] == n:
            blocking.append("No contact-angle measurements are linked to these specimens; the wettability comparison is impossible.")
        elif not ca.get("std"):
            blocking.append("Contact angle does not vary across records; its predictive value cannot be assessed.")
        if "concentration_value" in features and df.get("concentration_unit") is not None and df["concentration_unit"].dropna().nunique() > 1:
            blocking.append("Electrolyte concentrations are recorded in more than one unit; harmonise them or drop the concentration feature.")
        dups = int(df.duplicated(subset=[c for c in df.columns if c not in ("run_id",)]).sum())
        if dups:
            advisories.append(f"{dups} duplicate observation(s) (identical inputs and target).")
        per_group = df.groupby("specimen_code").size()
        if per_group.max() > 1:
            advisories.append(f"Repeated measurements on the same specimen (up to {int(per_group.max())}); evaluation keeps each specimen in one fold.")
    if groups < policy["min_groups_exploratory"]:
        blocking.append(f"{groups} independent specimen group(s); at least {policy['min_groups_exploratory']} are required for grouped cross-validation (configurable policy).")
    if report["demo_records"]:
        advisories.append("Dataset is DEMO - SYNTHETIC DATA. Results test the software only and say nothing about real materials.")
    level = "insufficient" if blocking else "exploratory" if groups < policy["min_groups_validated"] or report["demo_records"] else "adequate"
    if level == "exploratory":
        advisories.append(f"Exploratory only: fewer than {policy['min_groups_validated']} independent groups or synthetic data. Do not draw strong conclusions.")
    report.update(level=level, can_train=not blocking, validated_badge=level == "adequate", blocking=blocking, advisories=advisories,
                  n_splits=min(policy["max_folds"], groups) if groups >= 2 else 0)
    return report


def _pipeline(family: str, features: list[str], seed: int) -> Pipeline:
    if family == "mean":
        return Pipeline([("model", DummyRegressor(strategy="mean"))])
    num = [f for f in features if FEATURES[f][0] == "numeric"]
    cat = [f for f in features if FEATURES[f][0] == "categorical"]
    transformers = []
    if num:
        steps = [("impute", SimpleImputer(strategy="median"))] + ([("scale", StandardScaler())] if family == "linear" else [])
        transformers.append(("num", Pipeline(steps), num))
    if cat:
        transformers.append(("cat", Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="(missing)")),
                                              ("onehot", OneHotEncoder(handle_unknown="ignore"))]), cat))
    model = LinearRegression() if family == "linear" else RandomForestRegressor(n_estimators=300, random_state=seed, n_jobs=1)
    return Pipeline([("pre", ColumnTransformer(transformers, remainder="drop")), ("model", model)])


def regression_metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    err = pred - y
    out = {"mae": float(np.mean(np.abs(err))), "rmse": float(np.sqrt(np.mean(err**2))), "n": int(len(y))}
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if len(y) < 2 or ss_tot == 0:
        out.update(r2=None, r2_note="R^2 undefined: fewer than 2 held-out values or no variance in held-out targets.")
    else:
        out.update(r2=float(1 - np.sum(err**2) / ss_tot), r2_note=None)
    return out


def _frame(rows: list[dict], features: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for f in features:
        if f not in df:
            df[f] = np.nan
        if FEATURES[f][0] == "numeric":
            df[f] = pd.to_numeric(df[f], errors="coerce").astype(float)
        else:
            df[f] = df[f].astype(object).where(df[f].notna(), np.nan)
    return df


def train_comparison(rows: list[dict], target: str, baseline_features: list[str], transform: str, seed: int,
                     policy: dict, models_dir: Path, comparison_id: str) -> dict:
    validate_request(target, baseline_features, transform)
    report = readiness(rows, target, baseline_features, policy)
    if not report["can_train"]:
        raise MLError("Dataset not ready: " + " ".join(report["blocking"]))
    feats = [f for f in baseline_features if report["features"][f]["missing"] < report["n_records"]]
    df = _frame(rows, feats + [WETTABILITY_FEATURE])
    y_raw = df["target"].astype(float).to_numpy()
    if transform == "log10":
        if (y_raw <= 0).any():
            raise MLError("log10 transform requires strictly positive target values.")
        y = np.log10(y_raw)
    else:
        y = y_raw
    groups = df["specimen_code"].to_numpy()
    cv = GroupKFold(n_splits=report["n_splits"], shuffle=True, random_state=seed)
    folds = list(cv.split(df, y, groups))
    for tr, te in folds:  # guard: no specimen on both sides
        assert not set(groups[tr]) & set(groups[te])
    unit = TARGETS[target]["unit"]
    model_unit = f"log10({unit})" if transform == "log10" else unit
    versions = {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "numpy": np.__version__, "pandas": pd.__version__}
    domain = {f: ({"min": float(df[f].min()), "max": float(df[f].max())} if FEATURES[f][0] == "numeric" and df[f].notna().any()
                  else {"categories": sorted(map(str, df[f].dropna().unique()))}) for f in feats + [WETTABILITY_FEATURE]}
    runs = []
    for name, family, fset in CONFIGS:
        features = [] if fset == "none" else feats + ([WETTABILITY_FEATURE] if fset == "wettability" else [])
        oof = np.full(len(y), np.nan)
        fold_metrics = []
        for k, (tr, te) in enumerate(folds):
            pipe = _pipeline(family, features, seed)
            pipe.fit(df.iloc[tr][features] if features else np.zeros((len(tr), 1)), y[tr])
            pred = pipe.predict(df.iloc[te][features] if features else np.zeros((len(te), 1)))
            oof[te] = pred
            fold_metrics.append({"fold": k, "test_groups": sorted(map(str, set(groups[te]))), **regression_metrics(y[te], pred)})
        overall = regression_metrics(y, oof)
        maes = [m["mae"] for m in fold_metrics]
        overall.update(unit=model_unit, fold_mae_std=float(np.std(maes, ddof=1)) if len(maes) > 1 else None, folds=fold_metrics)
        if transform == "log10":
            overall["mae_original_units"] = float(np.mean(np.abs(10**oof - y_raw)))
        final = _pipeline(family, features, seed)
        final.fit(df[features] if features else np.zeros((len(y), 1)), y)
        path = models_dir / f"{comparison_id}_{family}_{fset}.joblib"
        joblib.dump(final, path)
        runs.append({
            "name": name, "model_family": family, "feature_set": fset, "features": features, "metrics": overall,
            "params": {"n_estimators": 300} if family == "random_forest" else {},
            "oof_predictions": [{"run_id": int(r), "specimen_code": str(g), "actual": float(a), "predicted": float(p)}
                                for r, g, a, p in zip(df["run_id"], groups, y, oof)],
            "model_path": path.name, "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "feature_domain": {f: domain[f] for f in features}, "software_versions": versions,
        })
    comparison = []
    for family in ("linear", "random_forest"):
        base = next(r for r in runs if r["model_family"] == family and r["feature_set"] == "baseline")
        wet = next(r for r in runs if r["model_family"] == family and r["feature_set"] == "wettability")
        deltas = [w["mae"] - b["mae"] for b, w in zip(base["metrics"]["folds"], wet["metrics"]["folds"])]
        comparison.append({"model_family": family, "baseline_mae": base["metrics"]["mae"], "wettability_mae": wet["metrics"]["mae"],
                           "delta_mae": wet["metrics"]["mae"] - base["metrics"]["mae"], "folds_improved": int(sum(d < 0 for d in deltas)),
                           "n_folds": len(deltas), "unit": model_unit})
    return {"readiness": report, "runs": runs, "comparison": comparison, "n_splits": len(folds), "model_unit": model_unit,
            "split_strategy": f"GroupKFold by specimen (shuffle, seed {seed})"}


def interpret(comparison: list[dict], level: str) -> str:
    """Conservative plain-language reading of the paired comparison."""
    parts = []
    for c in comparison:
        verb = "lower" if c["delta_mae"] < 0 else "higher" if c["delta_mae"] > 0 else "equal"
        parts.append(f"{c['model_family'].replace('_', ' ')}: adding contact angle gave {verb} out-of-fold MAE "
                     f"({c['baseline_mae']:.4g} -> {c['wettability_mae']:.4g} {c['unit']}; improved in {c['folds_improved']}/{c['n_folds']} folds)")
    caveat = ("Exploratory evaluation: too few independent specimens (or synthetic data) to treat any difference as evidence."
              if level != "adequate" else
              "Differences are descriptive; with this many groups, check fold-level consistency before claiming contact angle adds predictive value.")
    return "; ".join(parts) + ". " + caveat


def load_model(models_dir: Path, filename: str, sha256: str):
    path = (models_dir / filename).resolve()
    if models_dir.resolve() not in path.parents:
        raise MLError("Model path escapes the models directory.")
    if not path.exists():
        raise MLError("Model artifact file is missing; retrain the comparison.")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise MLError("Model artifact hash does not match the recorded hash; refusing to load it.")
    return joblib.load(path)  # only locally generated, hash-verified artifacts reach this line


def predict(model, run_features: list[str], domain: dict, transform: str, inputs: dict) -> dict:
    warnings = []
    row = {}
    for f in run_features:
        v = inputs.get(f)
        if FEATURES[f][0] == "numeric":
            v = None if v in (None, "") else float(v)
            d = domain.get(f, {})
            if v is None:
                warnings.append(f"'{f}' not provided; imputed with the training median.")
            elif d.get("min") is not None and not d["min"] <= v <= d["max"]:
                warnings.append(f"'{f}' = {v:g} is outside the training range [{d['min']:g}, {d['max']:g}]: extrapolation.")
        else:
            v = None if v in (None, "") else str(v)
            cats = domain.get(f, {}).get("categories", [])
            if v is None:
                warnings.append(f"'{f}' not provided; treated as '(missing)'.")
            elif v not in cats:
                warnings.append(f"'{f}' = '{v}' was not seen in training; its encoding is all-zero (unknown category).")
        row[f] = np.nan if v is None else v
    x = _frame([row], run_features)[run_features] if run_features else np.zeros((1, 1))
    raw = float(model.predict(x)[0])
    return {"prediction_model_space": raw, "prediction": 10**raw if transform == "log10" else raw, "warnings": warnings, "inputs": row}
