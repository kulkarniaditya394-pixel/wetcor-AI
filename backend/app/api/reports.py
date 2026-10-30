"""Experiment / ML reports, CSV exports and artifact downloads (by database id only, never by path)."""
from __future__ import annotations

import io

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import get_or_404
from app.api.corrosion import load_frame
from app.api.ml import get_comparison
from app.api.records import current_metrics
from app.database.models import (Artifact, ContactAngleRun, CorrosionAnalysis, CorrosionRun, DerivedMetric, Experiment, MLRun,
                                 Specimen)
from app.database.session import get_session
from app.services.electrochemistry.analysis import METHODS
from app.services.machine_learning.dataset import build_rows
from app.services.reporting import reports as R
from app.services.storage import StorageError, read_artifact, safe_filename

router = APIRouter(prefix="/api", tags=["reports"])


def _experiment_ctx(db: Session, exp: Experiment) -> dict:
    spec = db.get(Specimen, exp.specimen_id)
    cas = []
    for c in db.scalars(select(ContactAngleRun).where(ContactAngleRun.experiment_id == exp.id).order_by(ContactAngleRun.measured_at)).all():
        img = db.get(Artifact, c.image_artifact_id)
        ov = db.get(Artifact, c.overlay_artifact_id) if c.overlay_artifact_id else None
        try:
            ov_b64 = R.b64(read_artifact(ov)) if ov else None
        except StorageError:
            ov_b64 = None
        cas.append({"run": c, "sha256": img.sha256, "overlay_b64": ov_b64})
    ecs = []
    for run in db.scalars(select(CorrosionRun).where(CorrosionRun.experiment_id == exp.id).order_by(CorrosionRun.created_at)).all():
        raw = db.get(Artifact, run.raw_artifact_id)
        current = db.scalar(select(CorrosionAnalysis).where(CorrosionAnalysis.corrosion_run_id == run.id, CorrosionAnalysis.superseded.is_(False)))
        try:
            plot = R.corrosion_plot(run.method, load_frame(db, run), current.result if current else None, run.is_demo)
        except HTTPException:
            plot = "<p class='bad'>Processed data file missing or altered; plot unavailable.</p>"
        ecs.append({"run": run, "method_label": METHODS[run.method], "raw_filename": raw.original_filename, "raw_sha256": raw.sha256,
                    "metrics": current_metrics(db, run.id), "plot": plot, "notes": (current.result.get("notes", []) if current else [])})
    return {"specimen": spec, "experiment": exp, "contact_angles": cas, "corrosion": ecs, "is_demo": exp.is_demo or spec.is_demo}


@router.get("/reports/experiment/{experiment_id}")
def experiment_report(experiment_id: int, format: str = "html", db: Session = Depends(get_session)):
    exp = get_or_404(db, Experiment, experiment_id, "Experiment")
    ctx = _experiment_ctx(db, exp)
    if format == "json":
        return {"experiment_id": exp.id, "code": exp.code, "specimen": ctx["specimen"].code, "is_demo": ctx["is_demo"],
                "contact_angles": [{"id": c["run"].id, "mean_deg": c["run"].mean_deg, "method": c["run"].method, "image_sha256": c["sha256"]} for c in ctx["contact_angles"]],
                "corrosion_runs": [{"id": c["run"].id, "method": c["run"].method, "raw_sha256": c["raw_sha256"], "metrics": c["metrics"]} for c in ctx["corrosion"]]}
    return HTMLResponse(R.experiment_report(ctx))


@router.get("/reports/ml/{run_id}")
def ml_report(run_id: int, db: Session = Depends(get_session)):
    run = get_or_404(db, MLRun, run_id, "ML run")
    comp = get_comparison(run.comparison_id, db)
    runs = db.scalars(select(MLRun).where(MLRun.comparison_id == run.comparison_id).order_by(MLRun.id)).all()
    return HTMLResponse(R.ml_report(runs, comp["comparison"], comp["interpretation"]))


def _csv(df: pd.DataFrame, name: str, demo_note: bool) -> Response:
    buf = io.StringIO()
    if demo_note:
        buf.write("# Contains DEMO - SYNTHETIC DATA rows (is_demo = True)\n")
    df.to_csv(buf, index=False)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="wetcor_{name}.csv"'})


def _rows(db: Session, model, include_demo: bool) -> list:
    stmt = select(model)
    if hasattr(model, "is_demo") and not include_demo:
        stmt = stmt.where(model.is_demo.is_(False))
    return db.scalars(stmt.order_by(model.id)).all()


def _cols(obj, cols: list[str]) -> dict:
    return {c: getattr(obj, c) for c in cols}


@router.get("/exports/{kind}.csv")
def export(kind: str, include_demo: bool = False, target: str = "i_corr", comparison_id: str | None = None, db: Session = Depends(get_session)):
    codes = dict(db.execute(select(Specimen.id, Specimen.code)).all())
    if kind == "specimens":
        df = pd.DataFrame([_cols(s, ["id", "code", "material", "batch_source", "dimensions", "surface_preparation", "roughness_ra_um", "exposed_area_cm2", "notes", "is_demo", "created_at"])
                           for s in _rows(db, Specimen, include_demo)])
    elif kind == "experiments":
        df = pd.DataFrame([{**_cols(e, ["id", "code", "experiment_type", "performed_at", "operator", "electrolyte", "concentration_value", "concentration_unit", "temperature_c",
                                        "instrument", "reference_electrode", "status", "notes", "is_demo"]), "specimen_code": codes.get(e.specimen_id)} for e in _rows(db, Experiment, include_demo)])
    elif kind == "contact_angles":
        df = pd.DataFrame([{**_cols(c, ["id", "experiment_id", "method", "status", "left_deg", "right_deg", "mean_deg", "classification", "algorithm_version", "liquid",
                                        "droplet_volume_ul", "measured_at", "is_demo"]), "specimen_code": codes.get(c.specimen_id), "origin": "measured",
                            "image_sha256": db.get(Artifact, c.image_artifact_id).sha256, "warnings": " | ".join(c.warnings)} for c in _rows(db, ContactAngleRun, include_demo)])
    elif kind == "corrosion_runs":
        df = pd.DataFrame([{**_cols(r, ["id", "experiment_id", "method", "n_points", "exposed_area_cm2", "area_source", "reference_electrode", "instrument", "analysis_status", "is_demo"]),
                            "specimen_code": codes.get(r.specimen_id), "raw_filename": db.get(Artifact, r.raw_artifact_id).original_filename,
                            "raw_sha256": db.get(Artifact, r.raw_artifact_id).sha256} for r in _rows(db, CorrosionRun, include_demo)])
    elif kind == "metrics":
        stmt = select(DerivedMetric, CorrosionRun).join(CorrosionRun, CorrosionRun.id == DerivedMetric.corrosion_run_id).where(DerivedMetric.superseded.is_(False))
        if not include_demo:
            stmt = stmt.where(CorrosionRun.is_demo.is_(False))
        df = pd.DataFrame([{**_cols(m, ["corrosion_run_id", "analysis_id", "name", "label", "value", "unit", "origin", "formula", "method_version", "valid"]),
                            "specimen_code": codes.get(r.specimen_id), "method": r.method, "is_demo": r.is_demo, "parameters": m.parameters,
                            "warnings": " | ".join(m.warnings)} for m, r in db.execute(stmt).all()])
    elif kind == "dataset":
        rows, _ = build_rows(db, target, "demo" if include_demo else "real")
        df = pd.DataFrame(rows)
    elif kind in ("ml_runs", "ml_predictions"):
        stmt = select(MLRun).order_by(MLRun.id)
        if comparison_id:
            stmt = stmt.where(MLRun.comparison_id == comparison_id)
        runs = db.scalars(stmt).all()
        if kind == "ml_runs":
            df = pd.DataFrame([{**_cols(r, ["id", "comparison_id", "name", "model_family", "feature_set", "target", "target_unit", "target_transform", "n_records",
                                            "n_groups", "split_strategy", "seed", "readiness_level", "includes_demo", "dataset_hash", "created_at"]),
                                "features": ";".join(r.features), "mae": r.metrics.get("mae"), "rmse": r.metrics.get("rmse"), "r2": r.metrics.get("r2"),
                                "metric_unit": r.metrics.get("unit")} for r in runs])
        else:
            df = pd.DataFrame([{"ml_run_id": r.id, "comparison_id": r.comparison_id, "model": r.name, "origin": "predicted (out-of-fold)", **p,
                                "unit": r.metrics.get("unit"), "includes_demo": r.includes_demo} for r in runs for p in r.oof_predictions])
    else:
        raise HTTPException(404, f"Unknown export '{kind}'.")
    flag = next((c for c in ("is_demo", "includes_demo") if c in df), None)
    return _csv(df, kind, bool(flag) and bool(df[flag].astype(bool).any()))


@router.get("/artifacts/{artifact_id}")
def artifact_info(artifact_id: int, db: Session = Depends(get_session)):
    a = get_or_404(db, Artifact, artifact_id, "Artifact")
    return {"id": a.id, "kind": a.kind, "original_filename": a.original_filename, "sha256": a.sha256, "size_bytes": a.size_bytes,
            "content_type": a.content_type, "specimen_id": a.specimen_id, "experiment_id": a.experiment_id, "is_demo": a.is_demo, "meta": a.meta, "created_at": a.created_at}


@router.get("/artifacts/{artifact_id}/download")
def artifact_download(artifact_id: int, inline: bool = Query(False), db: Session = Depends(get_session)):
    a = get_or_404(db, Artifact, artifact_id, "Artifact")
    try:
        data = read_artifact(a)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from None
    disp = "inline" if inline and a.content_type.startswith("image/") else "attachment"
    name = safe_filename(a.original_filename)
    return Response(data, media_type=a.content_type, headers={"Content-Disposition": f'{disp}; filename="{name}"', "X-Content-SHA256": a.sha256,
                                                             "X-Content-Type-Options": "nosniff"})
