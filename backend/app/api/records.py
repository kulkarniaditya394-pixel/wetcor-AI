"""Specimens and experiments: CRUD, search, linked-record detail and guarded deletion."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import get_or_404
from app.database.models import Artifact, AuditEvent, ContactAngleRun, CorrosionRun, DerivedMetric, Experiment, Specimen
from app.database.session import get_session
from app.schemas.models import (CARunOut, CorrosionRunOut, ExperimentIn, ExperimentOut, ExperimentPatch, MetricOut, SpecimenIn,
                                SpecimenOut, SpecimenPatch)
from app.services.storage import audit

router = APIRouter(prefix="/api", tags=["records"])


def _page(db: Session, stmt, page: int, page_size: int, sort: str, sortable: dict):
    key = sort.lstrip("-")
    if key not in sortable:
        raise HTTPException(422, f"Cannot sort by '{key}'. Options: {', '.join(sortable)}")
    col = sortable[key]
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(col.desc() if sort.startswith("-") else col.asc()).offset((page - 1) * page_size).limit(page_size)).all()
    return rows, total


def _demo_filter(model, include_demo: bool, demo_only: bool):
    if demo_only:
        return model.is_demo.is_(True)
    return None if include_demo else model.is_demo.is_(False)


def _counts(db: Session, specimen_id: int) -> dict:
    return {
        "n_experiments": db.scalar(select(func.count()).where(Experiment.specimen_id == specimen_id)) or 0,
        "n_contact_angle": db.scalar(select(func.count()).where(ContactAngleRun.specimen_id == specimen_id)) or 0,
        "n_corrosion": db.scalar(select(func.count()).where(CorrosionRun.specimen_id == specimen_id)) or 0,
    }


def _history(db: Session, entity_type: str, entity_id: int) -> list[dict]:
    rows = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == entity_type, AuditEvent.entity_id == str(entity_id))
                      .order_by(AuditEvent.created_at.desc())).all()
    return [{"id": a.id, "action": a.action, "summary": a.summary, "details": a.details, "created_at": a.created_at} for a in rows]


def current_metrics(db: Session, run_id: int) -> list[dict]:
    rows = db.scalars(select(DerivedMetric).where(DerivedMetric.corrosion_run_id == run_id, DerivedMetric.superseded.is_(False)).order_by(DerivedMetric.id)).all()
    return [MetricOut.model_validate(m).model_dump() for m in rows]


# ---------------- specimens ----------------

SPEC_SORT = {"code": Specimen.code, "material": Specimen.material, "created_at": Specimen.created_at, "surface_preparation": Specimen.surface_preparation}


@router.get("/specimens")
def list_specimens(q: str | None = None, material: str | None = None, include_demo: bool = False, demo_only: bool = False,
                   sort: str = "-created_at", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500),
                   db: Session = Depends(get_session)):
    stmt = select(Specimen)
    if (f := _demo_filter(Specimen, include_demo, demo_only)) is not None:
        stmt = stmt.where(f)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Specimen.code.ilike(like), Specimen.material.ilike(like), Specimen.surface_preparation.ilike(like), Specimen.notes.ilike(like)))
    if material:
        stmt = stmt.where(Specimen.material == material)
    rows, total = _page(db, stmt, page, page_size, sort, SPEC_SORT)
    items = [{**SpecimenOut.model_validate(s).model_dump(), **_counts(db, s.id)} for s in rows]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/specimens", status_code=201, response_model=SpecimenOut)
def create_specimen(body: SpecimenIn, db: Session = Depends(get_session)):
    spec = Specimen(**body.model_dump())
    db.add(spec)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Specimen ID '{body.code}' already exists.") from None
    audit(db, "specimen", spec.id, "create", f"Specimen {spec.code} registered")
    db.commit()
    return spec


@router.get("/specimens/{specimen_id}")
def get_specimen(specimen_id: int, db: Session = Depends(get_session)):
    spec = get_or_404(db, Specimen, specimen_id, "Specimen")
    exps = db.scalars(select(Experiment).where(Experiment.specimen_id == spec.id).order_by(Experiment.created_at)).all()
    cas = db.scalars(select(ContactAngleRun).where(ContactAngleRun.specimen_id == spec.id).order_by(ContactAngleRun.created_at)).all()
    ecs = db.scalars(select(CorrosionRun).where(CorrosionRun.specimen_id == spec.id).order_by(CorrosionRun.created_at)).all()
    arts = db.scalars(select(Artifact).where(Artifact.specimen_id == spec.id).order_by(Artifact.created_at)).all()
    return {
        "specimen": SpecimenOut.model_validate(spec).model_dump(),
        "experiments": [ExperimentOut.model_validate(e).model_dump() for e in exps],
        "contact_angle_runs": [CARunOut.model_validate(c).model_dump(exclude={"auto_result", "diagnostics"}) for c in cas],
        "corrosion_runs": [{**CorrosionRunOut.model_validate(r).model_dump(), "metrics": current_metrics(db, r.id)} for r in ecs],
        "artifacts": [{"id": a.id, "kind": a.kind, "original_filename": a.original_filename, "sha256": a.sha256, "size_bytes": a.size_bytes,
                       "created_at": a.created_at} for a in arts],
        "history": _history(db, "specimen", spec.id),
    }


@router.patch("/specimens/{specimen_id}", response_model=SpecimenOut)
def update_specimen(specimen_id: int, body: SpecimenPatch, db: Session = Depends(get_session)):
    spec = get_or_404(db, Specimen, specimen_id, "Specimen")
    if spec.is_demo:
        raise HTTPException(422, "Demo specimens are read-only synthetic records.")
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(spec, k) for k in changes}
    for k, v in changes.items():
        setattr(spec, k, v)
    audit(db, "specimen", spec.id, "update", f"Specimen {spec.code} updated: {', '.join(changes) or 'no fields'}", {"before": before, "after": changes})
    db.commit()
    return spec


@router.delete("/specimens/{specimen_id}")
def delete_specimen(specimen_id: int, confirm: str = Query(..., description="Must equal the specimen ID"), db: Session = Depends(get_session)):
    spec = get_or_404(db, Specimen, specimen_id, "Specimen")
    if confirm != spec.code:
        raise HTTPException(400, "Confirmation text does not match the specimen ID.")
    counts = _counts(db, spec.id)
    if any(counts.values()) or db.scalar(select(func.count()).where(Artifact.specimen_id == spec.id)):
        raise HTTPException(409, f"Specimen {spec.code} has linked records ({counts}); delete or reassign them first. Raw measurements are never cascade-deleted.")
    audit(db, "specimen", spec.id, "delete", f"Specimen {spec.code} deleted", {"record": SpecimenOut.model_validate(spec).model_dump(mode="json")})
    db.delete(spec)
    db.commit()
    return {"deleted": spec.code}


# ---------------- experiments ----------------

EXP_SORT = {"code": Experiment.code, "created_at": Experiment.created_at, "performed_at": Experiment.performed_at, "status": Experiment.status}


@router.get("/experiments")
def list_experiments(q: str | None = None, specimen_id: int | None = None, status: str | None = None, include_demo: bool = False,
                     demo_only: bool = False, sort: str = "-created_at", page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=500),
                     db: Session = Depends(get_session)):
    stmt = select(Experiment)
    if (f := _demo_filter(Experiment, include_demo, demo_only)) is not None:
        stmt = stmt.where(f)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Experiment.code.ilike(like), Experiment.electrolyte.ilike(like), Experiment.operator.ilike(like), Experiment.notes.ilike(like)))
    if specimen_id:
        stmt = stmt.where(Experiment.specimen_id == specimen_id)
    if status:
        stmt = stmt.where(Experiment.status == status)
    rows, total = _page(db, stmt, page, page_size, sort, EXP_SORT)
    codes = dict(db.execute(select(Specimen.id, Specimen.code).where(Specimen.id.in_({e.specimen_id for e in rows}))).all()) if rows else {}
    items = []
    for e in rows:
        n_ca = db.scalar(select(func.count()).where(ContactAngleRun.experiment_id == e.id)) or 0
        n_ec = db.scalar(select(func.count()).where(CorrosionRun.experiment_id == e.id)) or 0
        items.append({**ExperimentOut.model_validate(e).model_dump(), "specimen_code": codes.get(e.specimen_id), "n_contact_angle": n_ca, "n_corrosion": n_ec})
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/experiments", status_code=201, response_model=ExperimentOut)
def create_experiment(body: ExperimentIn, db: Session = Depends(get_session)):
    spec = get_or_404(db, Specimen, body.specimen_id, "Specimen")
    if spec.is_demo:
        raise HTTPException(422, "Real experiments cannot be linked to DEMO synthetic specimens.")
    exp = Experiment(**body.model_dump())
    db.add(exp)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Experiment ID '{body.code}' already exists.") from None
    audit(db, "experiment", exp.id, "create", f"Experiment {exp.code} created for specimen {spec.code}")
    db.commit()
    return exp


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: int, db: Session = Depends(get_session)):
    exp = get_or_404(db, Experiment, experiment_id, "Experiment")
    spec = db.get(Specimen, exp.specimen_id)
    cas = db.scalars(select(ContactAngleRun).where(ContactAngleRun.experiment_id == exp.id)).all()
    ecs = db.scalars(select(CorrosionRun).where(CorrosionRun.experiment_id == exp.id)).all()
    return {
        "experiment": ExperimentOut.model_validate(exp).model_dump(),
        "specimen": SpecimenOut.model_validate(spec).model_dump(),
        "contact_angle_runs": [CARunOut.model_validate(c).model_dump(exclude={"auto_result", "diagnostics"}) for c in cas],
        "corrosion_runs": [{**CorrosionRunOut.model_validate(r).model_dump(), "metrics": current_metrics(db, r.id)} for r in ecs],
        "history": _history(db, "experiment", exp.id),
    }


@router.patch("/experiments/{experiment_id}", response_model=ExperimentOut)
def update_experiment(experiment_id: int, body: ExperimentPatch, db: Session = Depends(get_session)):
    exp = get_or_404(db, Experiment, experiment_id, "Experiment")
    if exp.is_demo:
        raise HTTPException(422, "Demo experiments are read-only synthetic records.")
    changes = body.model_dump(exclude_unset=True)
    before = {k: getattr(exp, k) for k in changes}
    for k, v in changes.items():
        setattr(exp, k, v)
    audit(db, "experiment", exp.id, "update", f"Experiment {exp.code} updated: {', '.join(changes) or 'no fields'}",
          {"before": {k: str(v) if v is not None else None for k, v in before.items()}, "after": {k: str(v) if v is not None else None for k, v in changes.items()}})
    db.commit()
    return exp


@router.delete("/experiments/{experiment_id}")
def delete_experiment(experiment_id: int, confirm: str = Query(...), db: Session = Depends(get_session)):
    exp = get_or_404(db, Experiment, experiment_id, "Experiment")
    if confirm != exp.code:
        raise HTTPException(400, "Confirmation text does not match the experiment ID.")
    linked = (db.scalar(select(func.count()).where(ContactAngleRun.experiment_id == exp.id)) or 0) + \
             (db.scalar(select(func.count()).where(CorrosionRun.experiment_id == exp.id)) or 0)
    if linked:
        raise HTTPException(409, f"Experiment {exp.code} has {linked} linked measurement(s); delete them first.")
    audit(db, "experiment", exp.id, "delete", f"Experiment {exp.code} deleted", {"record": ExperimentOut.model_validate(exp).model_dump(mode="json")})
    db.delete(exp)
    db.commit()
    return {"deleted": exp.code}
