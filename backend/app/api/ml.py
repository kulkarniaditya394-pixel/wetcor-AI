"""ML Studio: dataset readiness, grouped baseline vs contact-angle comparison, saved-model predictions."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import get_or_404, limits
from app.core.config import settings
from app.core.serial import clean
from app.database.models import MLRun
from app.database.session import get_session
from app.schemas.models import DatasetRequest, PredictRequest, TrainRequest
from app.services.machine_learning import core as C
from app.services.machine_learning.dataset import build_rows
from app.services.storage import audit

router = APIRouter(prefix="/api/ml", tags=["ml"])


def _run_dict(r: MLRun, full: bool = False) -> dict:
    d = {k: getattr(r, k) for k in ("id", "comparison_id", "name", "model_family", "feature_set", "features", "target", "target_unit",
                                     "target_transform", "dataset_hash", "n_records", "n_groups", "split_strategy", "n_splits", "seed",
                                     "readiness_level", "includes_demo", "status", "warnings", "created_at", "software_versions", "params")}
    m = dict(r.metrics)
    if not full:
        m.pop("folds", None)
    d["metrics"] = m
    if full:
        d.update(oof_predictions=r.oof_predictions, feature_domain=r.feature_domain, model_sha256=r.model_sha256, model_file=r.model_path)
    return d


@router.get("/options")
def options():
    return {"targets": C.TARGETS, "features": {k: {"kind": v[0], "label": v[1]} for k, v in C.FEATURES.items()},
            "wettability_feature": C.WETTABILITY_FEATURE, "configurations": [{"name": n, "family": f, "feature_set": s} for n, f, s in C.CONFIGS]}


@router.get("/dataset-summary")
def dataset_summary(data_source: str = "real", db: Session = Depends(get_session)):
    out = {}
    for t in C.TARGETS:
        rows, excluded = build_rows(db, t, data_source)
        out[t] = {"records": len(rows), "groups": len({r["specimen_code"] for r in rows}),
                  "with_contact_angle": sum(r["contact_angle_deg"] is not None for r in rows), "excluded": len(excluded)}
    return {"data_source": data_source, "targets": out, "policy": limits(db)["ml"]}


@router.post("/readiness-check")
def readiness_check(body: DatasetRequest, db: Session = Depends(get_session)):
    try:
        C.validate_request(body.target, body.baseline_features, body.target_transform)
    except C.MLError as exc:
        raise HTTPException(422, str(exc)) from None
    rows, excluded = build_rows(db, body.target, body.data_source)
    report = C.readiness(rows, body.target, body.baseline_features, limits(db)["ml"], excluded)
    if body.target_transform == "log10" and any(r["target"] <= 0 for r in rows):
        report["blocking"].append("log10 transform requires strictly positive targets.")
        report.update(can_train=False, level="insufficient", validated_badge=False)
    return clean({"readiness": report, "rows": rows, "dataset_hash": C.dataset_hash(rows, body.target, body.baseline_features)})


@router.post("/train")
def train(body: TrainRequest, db: Session = Depends(get_session)):
    policy = limits(db)["ml"]
    seed = body.seed if body.seed is not None else policy["default_seed"]
    rows, excluded = build_rows(db, body.target, body.data_source)
    comparison_id = uuid.uuid4().hex[:16]
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    try:
        out = C.train_comparison(rows, body.target, body.baseline_features, body.target_transform, seed, policy, settings.models_dir, comparison_id)
    except C.MLError as exc:
        raise HTTPException(422, str(exc)) from None
    out = clean(out)
    rep = out["readiness"]
    ds_hash = C.dataset_hash(rows, body.target, body.baseline_features)
    records = []
    for r in out["runs"]:
        run = MLRun(comparison_id=comparison_id, name=r["name"], model_family=r["model_family"], feature_set=r["feature_set"], features=r["features"],
                    target=body.target, target_unit=C.TARGETS[body.target]["unit"], target_transform=body.target_transform, params=r["params"],
                    dataset_hash=ds_hash, n_records=rep["n_records"], n_groups=rep["n_groups"], split_strategy=out["split_strategy"],
                    n_splits=out["n_splits"], seed=seed, metrics=r["metrics"], oof_predictions=r["oof_predictions"], feature_domain=r["feature_domain"],
                    readiness_level=rep["level"], includes_demo=body.data_source == "demo", model_path=r["model_path"], model_sha256=r["model_sha256"],
                    software_versions=r["software_versions"], warnings=rep["advisories"], status="recorded")
        db.add(run)
        records.append(run)
    db.flush()
    audit(db, "ml_comparison", comparison_id, "train",
          f"Trained {len(records)} configurations for {body.target} on {rep['n_records']} records / {rep['n_groups']} groups ({body.data_source}, {rep['level']})",
          {"dataset_hash": ds_hash, "excluded": excluded, "seed": seed})
    db.commit()
    return {"comparison_id": comparison_id, "readiness": rep, "runs": [_run_dict(r) for r in records], "comparison": out["comparison"],
            "interpretation": C.interpret(out["comparison"], rep["level"]), "excluded": excluded}


@router.get("/runs")
def list_runs(db: Session = Depends(get_session)):
    runs = db.scalars(select(MLRun).order_by(MLRun.created_at.desc(), MLRun.id)).all()
    groups: dict[str, dict] = {}
    for r in runs:
        g = groups.setdefault(r.comparison_id, {"comparison_id": r.comparison_id, "target": r.target, "created_at": r.created_at, "n_records": r.n_records,
                                                "n_groups": r.n_groups, "readiness_level": r.readiness_level, "includes_demo": r.includes_demo, "runs": []})
        g["runs"].append(_run_dict(r))
    return list(groups.values())


@router.get("/comparisons/{comparison_id}")
def get_comparison(comparison_id: str, db: Session = Depends(get_session)):
    runs = db.scalars(select(MLRun).where(MLRun.comparison_id == comparison_id).order_by(MLRun.id)).all()
    if not runs:
        raise HTTPException(404, "Comparison not found")
    comp = []
    for fam in ("linear", "random_forest"):
        b = next((r for r in runs if r.model_family == fam and r.feature_set == "baseline"), None)
        w = next((r for r in runs if r.model_family == fam and r.feature_set == "wettability"), None)
        if b and w:
            deltas = [x["mae"] - y["mae"] for y, x in zip(b.metrics["folds"], w.metrics["folds"])]
            comp.append({"model_family": fam, "baseline_mae": b.metrics["mae"], "wettability_mae": w.metrics["mae"], "delta_mae": w.metrics["mae"] - b.metrics["mae"],
                         "folds_improved": sum(d < 0 for d in deltas), "n_folds": len(deltas), "unit": b.metrics.get("unit")})
    return {"comparison_id": comparison_id, "runs": [_run_dict(r, full=True) for r in runs], "comparison": comp,
            "interpretation": C.interpret(comp, runs[0].readiness_level)}


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_session)):
    return _run_dict(get_or_404(db, MLRun, run_id, "ML run"), full=True)


@router.post("/predict")
def predict(body: PredictRequest, db: Session = Depends(get_session)):
    run = get_or_404(db, MLRun, body.run_id, "ML run")
    if not run.model_path or not run.model_sha256:
        raise HTTPException(409, "This run has no saved model.")
    try:
        model = C.load_model(settings.models_dir, run.model_path, run.model_sha256)
        out = C.predict(model, run.features, run.feature_domain, run.target_transform, body.inputs)
    except C.MLError as exc:
        raise HTTPException(409, str(exc)) from None
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, f"Invalid inputs: {exc}") from None
    warnings = out["warnings"]
    if run.readiness_level != "adequate":
        warnings.insert(0, f"Model evaluated on an {run.readiness_level} dataset ({run.n_groups} specimen groups): treat the prediction as illustrative only.")
    if run.includes_demo:
        warnings.insert(0, "Model trained on DEMO - SYNTHETIC DATA. This prediction says nothing about real materials.")
    return clean({"origin": "predicted", "label": "PREDICTED - not a measurement", "model": {"id": run.id, "name": run.name, "comparison_id": run.comparison_id,
                  "features": run.features, "dataset_hash": run.dataset_hash, "trained_at": run.created_at, "software_versions": run.software_versions},
                  "target": run.target, "target_unit": run.target_unit, "target_transform": run.target_transform, "prediction": out["prediction"],
                  "prediction_model_space": out["prediction_model_space"], "inputs": out["inputs"], "warnings": warnings,
                  "validation": {k: run.metrics.get(k) for k in ("mae", "rmse", "r2", "r2_note", "unit", "fold_mae_std")} | {"n_groups": run.n_groups,
                                 "split_strategy": run.split_strategy, "readiness_level": run.readiness_level},
                  "uncertainty": "No prediction interval is reported: none has been validated for this model."})
