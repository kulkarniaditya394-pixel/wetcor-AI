"""Contact-angle analysis and measurement records.

/analyze is stateless. Saving re-runs the analysis on the server from the stored original image and
the submitted parameters, so stored values are always reproducible from stored inputs. When the
saved result used manual corrections, the purely automatic result is stored separately.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import check_links, get_or_404, limits, parse_form_json, read_upload
from app.api.records import _history
from app.core.serial import clean
from app.database.models import Artifact, ContactAngleRun, utcnow
from app.database.session import get_session
from app.schemas.models import CAMeasurementMeta, CAParams, CAPatch, CARunOut
from app.services import quick
from app.services.storage import StorageError, audit, read_artifact, store_artifact
from app.services.wettability.detection import analyze
from app.services.wettability.overlay import render_overlay

router = APIRouter(prefix="/api/wettability", tags=["wettability"])
IMAGE_TYPES = {"image/png", "image/jpeg", "image/bmp", "image/tiff", "image/x-ms-bmp", "application/octet-stream"}


def _run(data: bytes, params: CAParams, lim: dict) -> dict:
    return clean(analyze(data, params.model_dump(exclude_none=True), lim))


def _auto_only(params: CAParams) -> CAParams:
    return CAParams(roi=params.roi, primary_method=params.primary_method)


@router.post("/analyze")
async def analyze_image(image: UploadFile = File(...), params: str | None = Form(None), include_auto: bool = Form(True),
                        db: Session = Depends(get_session)):
    if image.content_type not in IMAGE_TYPES:
        raise HTTPException(415, f"Unsupported image type {image.content_type}.")
    data = await read_upload(image)
    p = parse_form_json(params, CAParams)
    return quick.wettability_analyze(data, p.model_dump(exclude_none=True), limits(db)["wettability"], include_auto)


@router.post("/measurements", status_code=201)
async def save_measurement(image: UploadFile = File(...), params: str | None = Form(None), meta: str = Form(...),
                           db: Session = Depends(get_session)):
    data = await read_upload(image)
    p = parse_form_json(params, CAParams)
    m = parse_form_json(meta, CAMeasurementMeta)
    spec, _ = check_links(db, m.specimen_id, m.experiment_id)
    if spec.is_demo:
        raise HTTPException(422, "Measurements cannot be saved against DEMO synthetic specimens.")
    lim = limits(db)["wettability"]
    result = _run(data, p, lim)
    if result["status"] == "failed" and m.status == "accepted":
        raise HTTPException(422, "No reliable angle was obtained; correct the analysis or save the image as rejected. " + " ".join(result["errors"]))
    if m.status == "rejected" and not m.rejection_reason:
        raise HTTPException(422, "A rejection reason is required.")
    auto = _run(data, _auto_only(p), lim) if result.get("manual_correction") else None
    raw = store_artifact(db, data, kind="raw_image", subdir="raw/images", original_filename=image.filename or "capture.png",
                         content_type=image.content_type or "image/png", specimen_id=spec.id, experiment_id=m.experiment_id,
                         meta={"width": (result.get("image") or {}).get("width"), "height": (result.get("image") or {}).get("height")})
    overlay = None
    if result.get("image"):
        overlay = store_artifact(db, render_overlay(data, result), kind="overlay_image", subdir="processed/overlays",
                                 original_filename=f"overlay_{raw.sha256[:12]}.png", content_type="image/png",
                                 specimen_id=spec.id, experiment_id=m.experiment_id, meta={"source_artifact_id": raw.id})
    run = ContactAngleRun(
        specimen_id=spec.id, experiment_id=m.experiment_id, image_artifact_id=raw.id, overlay_artifact_id=overlay.id if overlay else None,
        method=result["method"] or ({"manual_tangent": "manual_tangent", "three_point": "manual_three_point"}.get(p.mode, "auto_failed")), status=m.status,
        left_deg=result["left_deg"], right_deg=result["right_deg"], mean_deg=result["mean_deg"],
        classification=(result["classification"] or {}).get("label"), analysis_params=p.model_dump(exclude_none=True),
        diagnostics={k: result.get(k) for k in ("status", "diagnostics", "methods", "geometry", "limits", "params", "lr_diff_deg",
                                                 "classification", "errors", "uncertainty_note", "fit_method", "image")},
        warnings=result["warnings"], auto_result=auto, algorithm_version=result["algorithm_version"], liquid=m.liquid,
        droplet_volume_ul=m.droplet_volume_ul, captured_at=m.captured_at, measured_at=utcnow(), rejection_reason=m.rejection_reason,
        notes=m.notes,
    )
    db.add(run)
    db.flush()
    audit(db, "contact_angle_run", run.id, "create",
          f"Contact angle saved for {spec.code}: {run.mean_deg if run.mean_deg is not None else 'n/a'} deg ({run.method}, {run.status})",
          {"image_sha256": raw.sha256, "method": run.method})
    if auto is not None:
        audit(db, "contact_angle_run", run.id, "manual_correction",
              f"Manual correction applied: automatic {auto.get('mean_deg')} deg -> corrected {run.mean_deg} deg",
              {"automatic": {k: auto.get(k) for k in ("status", "left_deg", "right_deg", "mean_deg", "method")},
               "corrected": {"left_deg": run.left_deg, "right_deg": run.right_deg, "mean_deg": run.mean_deg}, "params": run.analysis_params})
    db.commit()
    return CARunOut.model_validate(run).model_dump()


@router.get("/measurements")
def list_measurements(specimen_id: int | None = None, experiment_id: int | None = None, include_demo: bool = False,
                      limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_session)):
    stmt = select(ContactAngleRun).order_by(ContactAngleRun.created_at.desc()).limit(limit)
    if not include_demo:
        stmt = stmt.where(ContactAngleRun.is_demo.is_(False))
    if specimen_id:
        stmt = stmt.where(ContactAngleRun.specimen_id == specimen_id)
    if experiment_id:
        stmt = stmt.where(ContactAngleRun.experiment_id == experiment_id)
    return [CARunOut.model_validate(r).model_dump(exclude={"auto_result", "diagnostics"}) for r in db.scalars(stmt).all()]


@router.get("/measurements/{run_id}")
def get_measurement(run_id: int, db: Session = Depends(get_session)):
    run = get_or_404(db, ContactAngleRun, run_id, "Contact-angle measurement")
    img = db.get(Artifact, run.image_artifact_id)
    integrity = "ok"
    try:
        read_artifact(img)
    except StorageError as exc:
        integrity = str(exc)
    return {**CARunOut.model_validate(run).model_dump(), "image": {"id": img.id, "sha256": img.sha256, "original_filename": img.original_filename,
                                                                    "integrity": integrity},
            "history": _history(db, "contact_angle_run", run.id)}


@router.patch("/measurements/{run_id}")
def update_measurement(run_id: int, body: CAPatch, db: Session = Depends(get_session)):
    run = get_or_404(db, ContactAngleRun, run_id, "Contact-angle measurement")
    if run.is_demo:
        raise HTTPException(422, "Demo measurements are read-only synthetic records.")
    changes = body.model_dump(exclude_unset=True, exclude={"reanalyse_params", "reason"})
    if "experiment_id" in changes:
        check_links(db, run.specimen_id, changes["experiment_id"])
    if changes.get("status") == "rejected" and not (changes.get("rejection_reason") or run.rejection_reason):
        raise HTTPException(422, "A rejection reason is required.")
    before = {k: getattr(run, k) for k in changes}
    for k, v in changes.items():
        setattr(run, k, v)
    if changes:
        audit(db, "contact_angle_run", run.id, "update", f"Metadata updated: {', '.join(changes)}", {"before": before, "after": changes, "reason": body.reason})
    if body.reanalyse_params is not None:
        img = db.get(Artifact, run.image_artifact_id)
        try:
            data = read_artifact(img)
        except StorageError as exc:
            raise HTTPException(409, str(exc)) from None
        result = _run(data, body.reanalyse_params, limits(db)["wettability"])
        if result["status"] == "failed":
            raise HTTPException(422, "Re-analysis failed: " + " ".join(result["errors"]))
        previous = {"method": run.method, "left_deg": run.left_deg, "right_deg": run.right_deg, "mean_deg": run.mean_deg,
                    "analysis_params": run.analysis_params, "overlay_artifact_id": run.overlay_artifact_id}
        overlay = store_artifact(db, render_overlay(data, result), kind="overlay_image", subdir="processed/overlays",
                                 original_filename=f"overlay_{img.sha256[:12]}_rev.png", content_type="image/png",
                                 specimen_id=run.specimen_id, experiment_id=run.experiment_id, meta={"source_artifact_id": img.id})
        if run.auto_result is None and not run.method.startswith("manual"):
            run.auto_result = {k: run.diagnostics.get(k) for k in ("status", "methods", "classification")} | previous
        run.method, run.left_deg, run.right_deg, run.mean_deg = result["method"], result["left_deg"], result["right_deg"], result["mean_deg"]
        run.classification = (result["classification"] or {}).get("label")
        run.analysis_params = body.reanalyse_params.model_dump(exclude_none=True)
        run.diagnostics = {k: result.get(k) for k in ("status", "diagnostics", "methods", "geometry", "limits", "params", "lr_diff_deg",
                                                       "classification", "errors", "uncertainty_note", "fit_method", "image")}
        run.warnings, run.overlay_artifact_id, run.algorithm_version = result["warnings"], overlay.id, result["algorithm_version"]
        audit(db, "contact_angle_run", run.id, "reanalysis", f"Re-analysed: {previous['mean_deg']} deg -> {run.mean_deg} deg ({run.method})",
              {"previous": previous, "new": {"method": run.method, "left_deg": run.left_deg, "right_deg": run.right_deg, "mean_deg": run.mean_deg,
                                              "analysis_params": run.analysis_params}, "reason": body.reason})
    db.commit()
    return CARunOut.model_validate(run).model_dump()


@router.delete("/measurements/{run_id}")
def delete_measurement(run_id: int, confirm: str = Query(...), db: Session = Depends(get_session)):
    from app.services.storage import move_to_trash
    run = get_or_404(db, ContactAngleRun, run_id, "Contact-angle measurement")
    if confirm != f"CA-{run.id}":
        raise HTTPException(400, f"Type CA-{run.id} to confirm deletion.")
    trashed = {}
    for aid in (run.image_artifact_id, run.overlay_artifact_id):
        if aid and (a := db.get(Artifact, aid)):
            trashed[a.sha256] = move_to_trash(a)
    audit(db, "contact_angle_run", run.id, "delete", f"Contact-angle measurement {run.id} deleted; files moved to data/trash",
          {"record": CARunOut.model_validate(run).model_dump(mode="json"), "trashed_files": trashed})
    db.delete(run)
    db.flush()
    for aid in (run.image_artifact_id, run.overlay_artifact_id):
        if aid and (a := db.get(Artifact, aid)) and not db.scalar(select(ContactAngleRun.id).where(
                (ContactAngleRun.image_artifact_id == aid) | (ContactAngleRun.overlay_artifact_id == aid))):
            db.delete(a)
    db.commit()
    return {"deleted": run_id, "trashed_files": list(trashed.values())}
