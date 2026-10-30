"""Potentiostat file import (preview -> mapped import) and electrochemical analysis."""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import check_links, get_or_404, limits, parse_form_json, read_upload
from app.api.records import _history, current_metrics
from app.core.serial import clean
from app.database.models import Artifact, CorrosionAnalysis, CorrosionRun, DerivedMetric
from app.database.session import get_session
from app.schemas.models import AnalyzeRequest, CorrosionRunOut, ImportMeta
from app.services.electrochemistry import analysis as A
from app.services.electrochemistry import materials as MAT
from app.services.electrochemistry.parser import ParseError, parse_table, suggest_mapping
from app.services.electrochemistry.units import CANONICAL, FACTORS, UnitError
from app.services.storage import StorageError, audit, move_to_trash, read_artifact, store_artifact

router = APIRouter(prefix="/api/corrosion", tags=["corrosion"])
TEXT_EXT = (".csv", ".tsv", ".txt", ".dta", ".dat")


def _check_ext(name: str | None) -> None:
    if not (name or "").lower().endswith(TEXT_EXT):
        raise HTTPException(415, f"Unsupported file type. Accepted: {', '.join(TEXT_EXT)} (delimited text exports).")


@router.get("/methods")
def methods():
    return {"methods": A.METHODS, "required": {m: [list(g) for g in r] for m, r in A.REQUIRED.items()},
            "allowed_roles": {m: sorted(r) for m, r in A.ALLOWED.items()}, "units": FACTORS, "canonical": CANONICAL,
            "materials": MAT.all_profiles()}


@router.post("/import/preview")
async def preview(file: UploadFile = File(...)):
    _check_ext(file.filename)
    data = await read_upload(file)
    try:
        t = parse_table(data)
    except ParseError as exc:
        raise HTTPException(422, str(exc)) from None
    return clean({
        "filename": file.filename, "size_bytes": len(data), "encoding": t.encoding, "delimiter": t.delimiter, "decimal_comma": t.decimal_comma,
        "columns": t.columns, "units_row": t.units_row, "n_rows": int(len(t.data)), "header_line": t.header_line, "data_start_line": t.data_start_line,
        "metadata": t.metadata, "warnings": t.warnings, "preview_rows": t.preview_rows(20),
        "raw_head": data[:3000].decode(t.encoding if t.encoding != "utf-8-sig" else "utf-8", errors="replace").splitlines()[:40],
        "suggestion": suggest_mapping(t.columns, t.units_row, t.data),
        "columns_data": {c: t.data[: min(len(t.data), 4000), k] for k, c in enumerate(t.columns)},
    })


@router.post("/import", status_code=201)
async def import_run(file: UploadFile = File(...), meta: str = Form(...), db: Session = Depends(get_session)):
    _check_ext(file.filename)
    data = await read_upload(file)
    m = parse_form_json(meta, ImportMeta)
    spec, exp = check_links(db, m.specimen_id, m.experiment_id)
    if spec.is_demo:
        raise HTTPException(422, "Runs cannot be imported against DEMO synthetic specimens.")
    area, area_source = m.exposed_area_cm2, m.area_source
    if area is None and spec.exposed_area_cm2:
        area, area_source = spec.exposed_area_cm2, "specimen record"
    elif area is not None:
        area_source = area_source or "entered at import"
    try:
        t = parse_table(data)
        df, warnings = A.build_dataset(t, m.method, m.mapping, m.units, imag_convention=m.imag_convention, area_cm2=area, anodic_negative=m.anodic_negative)
    except (ParseError, A.AnalysisError, UnitError) as exc:
        raise HTTPException(422, str(exc)) from None
    return _store_run(db, data, file.filename or "data.csv", t, df, warnings, m, spec, exp, area, area_source)


def _store_run(db: Session, data: bytes, filename: str, t, df: pd.DataFrame, warnings: list[str], m: ImportMeta, spec, exp,
               area: float | None, area_source: str | None, is_demo: bool = False) -> dict:
    raw = store_artifact(db, data, kind="raw_data", subdir="raw/instrument", original_filename=filename, content_type="text/plain",
                         specimen_id=spec.id, experiment_id=exp.id if exp else None, is_demo=is_demo,
                         meta={"encoding": t.encoding, "delimiter": t.delimiter})
    buf = io.StringIO()
    buf.write(f"# WETCOR AI processed data ({'DEMO - SYNTHETIC' if is_demo else 'from instrument file'}); canonical units; source sha256 {raw.sha256}\n")
    df.to_csv(buf, index=False)
    proc = store_artifact(db, buf.getvalue().encode(), kind="processed_data", subdir="processed/data", original_filename=f"run_{raw.sha256[:12]}_{m.method}.csv",
                          content_type="text/csv", specimen_id=spec.id, experiment_id=exp.id if exp else None, is_demo=is_demo,
                          meta={"source_artifact_id": raw.id})
    run = CorrosionRun(
        specimen_id=spec.id, experiment_id=exp.id if exp else None, raw_artifact_id=raw.id, processed_artifact_id=proc.id, method=m.method,
        column_mapping={k: v for k, v in m.mapping.items() if v}, units={k: v for k, v in m.units.items() if k in m.mapping},
        import_meta=clean({"encoding": t.encoding, "delimiter": t.delimiter, "decimal_comma": t.decimal_comma, "header_line": t.header_line,
                           "data_start_line": t.data_start_line, "metadata": t.metadata, "imag_convention": m.imag_convention,
                           "anodic_negative": m.anodic_negative, "columns": t.columns, "units_row": t.units_row}),
        parser_warnings=t.warnings + warnings, exposed_area_cm2=area, area_source=area_source,
        reference_electrode=m.reference_electrode or (exp.reference_electrode if exp else None), instrument=m.instrument or (exp.instrument if exp else None),
        n_points=len(df), notes=m.notes, is_demo=is_demo,
    )
    db.add(run)
    db.flush()
    audit(db, "corrosion_run", run.id, "import", f"{A.METHODS[m.method]} file '{filename}' imported for {spec.code} ({len(df)} points)",
          {"raw_sha256": raw.sha256, "mapping": run.column_mapping, "units": run.units})
    db.commit()
    return CorrosionRunOut.model_validate(run).model_dump()


def load_frame(db: Session, run: CorrosionRun) -> pd.DataFrame:
    try:
        data = read_artifact(db.get(Artifact, run.processed_artifact_id))
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from None
    return pd.read_csv(io.BytesIO(data), comment="#")


def _material(body: AnalyzeRequest) -> dict | None:
    if not body.material:
        return None
    mat = body.material.model_dump()
    if mat.get("profile"):
        if mat["profile"] not in MAT.PROFILES:
            raise HTTPException(422, f"Unknown material profile '{mat['profile']}'.")
        prof = MAT.profile(mat["profile"])
        mat = {**prof, "is_alloy": False, "profile": prof["key"]}
    if not any(mat.get(k) is not None for k in ("equivalent_weight_g_eq", "density_g_cm3")):
        return None
    return mat


def run_analysis(db: Session, run: CorrosionRun, body: AnalyzeRequest) -> dict:
    lim = limits(db)["electrochemistry"]
    try:
        result = A.analyze(run.method, load_frame(db, run), body.params, lim, area_cm2=run.exposed_area_cm2,
                           reference_electrode=run.reference_electrode, material=_material(body))
    except (A.AnalysisError, UnitError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, f"Analysis failed: {exc}") from None
    result = clean(result)
    if body.material:
        result["material"] = body.material.model_dump()
    prev = db.scalars(select(CorrosionAnalysis).where(CorrosionAnalysis.corrosion_run_id == run.id, CorrosionAnalysis.superseded.is_(False))).all()
    for p in prev:
        p.superseded = True
    for mtr in db.scalars(select(DerivedMetric).where(DerivedMetric.corrosion_run_id == run.id, DerivedMetric.superseded.is_(False))).all():
        mtr.superseded = True
    rec = CorrosionAnalysis(corrosion_run_id=run.id, method=run.method, method_version=result["method_version"], params=clean(body.params),
                            result={k: v for k, v in result.items() if k != "metrics"}, status=result["status"])
    db.add(rec)
    db.flush()
    for mt in result["metrics"]:
        db.add(DerivedMetric(corrosion_run_id=run.id, analysis_id=rec.id, method_version=result["method_version"], **mt))
    run.analysis_status = {"ok": "analysed", "limited": "analysis_limited", "invalid": "analysis_invalid"}[result["status"]]
    audit(db, "corrosion_run", run.id, "reanalysis" if prev else "analysis",
          f"{A.METHODS[run.method]} analysed ({result['status']}); {len(result['metrics'])} metric(s)" + (f"; supersedes analysis {prev[0].id}" if prev else ""),
          {"analysis_id": rec.id, "params": clean(body.params), "superseded": [p.id for p in prev]})
    db.commit()
    return {"analysis_id": rec.id, **result}


@router.post("/runs/{run_id}/analyze")
def analyze_run(run_id: int, body: AnalyzeRequest, db: Session = Depends(get_session)):
    run = get_or_404(db, CorrosionRun, run_id, "Corrosion run")
    return run_analysis(db, run, body)  # demo runs may be re-analysed; results stay demo-labelled via the run


@router.get("/runs")
def list_runs(specimen_id: int | None = None, experiment_id: int | None = None, method: str | None = None, include_demo: bool = False,
              limit: int = Query(200, ge=1, le=2000), db: Session = Depends(get_session)):
    stmt = select(CorrosionRun).order_by(CorrosionRun.created_at.desc()).limit(limit)
    if not include_demo:
        stmt = stmt.where(CorrosionRun.is_demo.is_(False))
    if specimen_id:
        stmt = stmt.where(CorrosionRun.specimen_id == specimen_id)
    if experiment_id:
        stmt = stmt.where(CorrosionRun.experiment_id == experiment_id)
    if method:
        stmt = stmt.where(CorrosionRun.method == method)
    return [CorrosionRunOut.model_validate(r).model_dump() for r in db.scalars(stmt).all()]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_session)):
    run = get_or_404(db, CorrosionRun, run_id, "Corrosion run")
    raw = db.get(Artifact, run.raw_artifact_id)
    integrity = "ok"
    try:
        read_artifact(raw)
    except StorageError as exc:
        integrity = str(exc)
    current = db.scalar(select(CorrosionAnalysis).where(CorrosionAnalysis.corrosion_run_id == run.id, CorrosionAnalysis.superseded.is_(False)))
    analyses = db.scalars(select(CorrosionAnalysis).where(CorrosionAnalysis.corrosion_run_id == run.id).order_by(CorrosionAnalysis.created_at.desc())).all()
    return {**CorrosionRunOut.model_validate(run).model_dump(),
            "raw_file": {"id": raw.id, "original_filename": raw.original_filename, "sha256": raw.sha256, "size_bytes": raw.size_bytes, "integrity": integrity},
            "current_analysis": ({"analysis_id": current.id, "params": current.params, "status": current.status, **current.result} if current else None),
            "analyses": [{"id": a.id, "status": a.status, "params": a.params, "superseded": a.superseded, "created_at": a.created_at} for a in analyses],
            "metrics": current_metrics(db, run.id), "history": _history(db, "corrosion_run", run.id)}


@router.get("/runs/{run_id}/data")
def run_data(run_id: int, db: Session = Depends(get_session)):
    run = get_or_404(db, CorrosionRun, run_id, "Corrosion run")
    df = load_frame(db, run)
    out = {c: df[c].tolist() for c in df.columns}
    if "current_density_A_cm2" in df:
        lc = A.log_current(df["current_density_A_cm2"].to_numpy())
        out["log10_abs_current_density"] = lc["log10_abs"]
        out["log_excluded_zero"] = lc["excluded_zero"]
    if "z_real_ohm" in df:
        out["z_mod_calc_ohm"] = np.hypot(df["z_real_ohm"], df["z_imag_ohm"])
        out["phase_calc_deg"] = np.degrees(np.arctan2(df["z_imag_ohm"], df["z_real_ohm"]))
    return clean({"run_id": run.id, "method": run.method, "n_points": len(df), "columns": list(df.columns), "data": out})


@router.get("/runs/{run_id}/metrics")
def run_metrics(run_id: int, include_superseded: bool = False, db: Session = Depends(get_session)):
    get_or_404(db, CorrosionRun, run_id, "Corrosion run")
    from app.schemas.models import MetricOut
    stmt = select(DerivedMetric).where(DerivedMetric.corrosion_run_id == run_id)
    if not include_superseded:
        stmt = stmt.where(DerivedMetric.superseded.is_(False))
    return [MetricOut.model_validate(m).model_dump() for m in db.scalars(stmt.order_by(DerivedMetric.created_at.desc())).all()]


@router.get("/runs/{run_id}/processed.csv")
def processed_csv(run_id: int, db: Session = Depends(get_session)):
    run = get_or_404(db, CorrosionRun, run_id, "Corrosion run")
    art = db.get(Artifact, run.processed_artifact_id)
    try:
        data = read_artifact(art)
    except StorageError as exc:
        raise HTTPException(409, str(exc)) from None
    return Response(data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="corrosion_run_{run.id}_processed.csv"'})


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, confirm: str = Query(...), db: Session = Depends(get_session)):
    run = get_or_404(db, CorrosionRun, run_id, "Corrosion run")
    if confirm != f"EC-{run.id}":
        raise HTTPException(400, f"Type EC-{run.id} to confirm deletion.")
    arts = [db.get(Artifact, run.raw_artifact_id), db.get(Artifact, run.processed_artifact_id)]
    trashed = {a.sha256: move_to_trash(a) for a in arts if a}
    audit(db, "corrosion_run", run.id, "delete", f"Corrosion run {run.id} deleted; files moved to data/trash",
          {"record": CorrosionRunOut.model_validate(run).model_dump(mode="json"), "trashed_files": trashed})
    for mt in db.scalars(select(DerivedMetric).where(DerivedMetric.corrosion_run_id == run.id)).all():
        db.delete(mt)
    db.flush()
    for an in db.scalars(select(CorrosionAnalysis).where(CorrosionAnalysis.corrosion_run_id == run.id)).all():
        db.delete(an)
    db.flush()
    db.delete(run)
    db.flush()
    for a in arts:
        if a:
            db.delete(a)
    db.commit()
    return {"deleted": run_id, "trashed_files": list(trashed.values())}
