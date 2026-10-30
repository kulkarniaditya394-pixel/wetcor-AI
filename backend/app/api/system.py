"""Health, version, settings, dashboard and reference data."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.common import limits
from app.core import defaults as D
from app.core.config import APP_NAME, APP_VERSION, settings
from app.database.models import (AppSetting, AuditEvent, ContactAngleRun, CorrosionRun, DerivedMetric, Experiment, MLRun,
                                 Specimen)
from app.database.session import get_session
from app.schemas.models import SettingsIn
from app.services.electrochemistry.analysis import METHOD_VERSION
from app.services.electrochemistry.materials import all_profiles
from app.services.storage import audit
from app.services.wettability.detection import ALGORITHM_VERSION

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_session)):
    try:
        db.execute(text("SELECT 1"))
        version = db.execute(text("PRAGMA user_version")).scalar()
    except Exception:  # noqa: BLE001 - report, do not crash
        raise HTTPException(503, "Database unavailable") from None
    writable = all((settings.data_dir / d).is_dir() for d in ("raw", "processed", "database"))
    return {"status": "ok" if writable else "degraded", "database": "ok", "schema_version": version, "storage_writable": writable}


@router.get("/version")
def version():
    return {"name": APP_NAME, "version": APP_VERSION, "contact_angle_algorithm": ALGORITHM_VERSION, "electrochemistry_methods": METHOD_VERSION}


@router.get("/settings")
def get_settings(db: Session = Depends(get_session)):
    return {"analysis": limits(db), "spec": {s: {k: {"default": v[0], "description": v[1]} for k, v in items.items()} for s, items in D.SPEC.items()},
            "data_dir": "data/ (inside the WETCOR AI folder)" if settings.data_dir.name == "data" else "custom WETCOR_DATA_DIR"}


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_session)):
    merged = D.merge(body.analysis)
    row = db.get(AppSetting, "analysis")
    before = row.value if row else None
    if row:
        row.value = merged
    else:
        db.add(AppSetting(key="analysis", value=merged))
    audit(db, "settings", "analysis", "update", "Analysis limits updated", {"before": before, "after": merged})
    db.commit()
    return {"analysis": merged}


@router.get("/materials")
def materials():
    return all_profiles()


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_session)):
    def count(model, demo: bool, *where):
        return db.scalar(select(func.count()).select_from(model).where(model.is_demo.is_(demo), *where)) or 0

    def counts(demo: bool):
        eligible = db.scalar(
            select(func.count(func.distinct(DerivedMetric.corrosion_run_id))).join(CorrosionRun, CorrosionRun.id == DerivedMetric.corrosion_run_id)
            .where(DerivedMetric.name.in_(("i_corr", "corrosion_rate", "rp")), DerivedMetric.valid.is_(True), DerivedMetric.superseded.is_(False),
                   CorrosionRun.is_demo.is_(demo),
                   CorrosionRun.specimen_id.in_(select(ContactAngleRun.specimen_id).where(ContactAngleRun.status == "accepted", ContactAngleRun.mean_deg.is_not(None))))
        ) or 0
        return {
            "specimens": count(Specimen, demo),
            "contact_angle_runs": count(ContactAngleRun, demo),
            "corrosion_runs": count(CorrosionRun, demo),
            "experiments": count(Experiment, demo),
            "completed_experiments": count(Experiment, demo, Experiment.status == "complete"),
            "ml_eligible_records": eligible,
        }

    real = counts(False)
    specs = db.scalars(select(Specimen).where(Specimen.is_demo.is_(False))).all()
    with_ca = set(db.scalars(select(ContactAngleRun.specimen_id).where(ContactAngleRun.status == "accepted")).all())
    with_ec = set(db.scalars(select(CorrosionRun.specimen_id)).all())
    completeness = {
        "specimens_total": len(specs),
        "with_contact_angle": sum(s.id in with_ca for s in specs),
        "with_corrosion": sum(s.id in with_ec for s in specs),
        "with_both": sum(s.id in with_ca and s.id in with_ec for s in specs),
        "with_exposed_area": sum(s.exposed_area_cm2 is not None for s in specs),
    }
    recent_exp = db.scalars(select(Experiment).order_by(Experiment.created_at.desc()).limit(6)).all()
    activity = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(10)).all()
    return {
        "real": real, "demo": counts(True), "completeness": completeness,
        "ml_runs": db.scalar(select(func.count(func.distinct(MLRun.comparison_id)))) or 0,
        "recent_experiments": [{"id": e.id, "code": e.code, "specimen_id": e.specimen_id, "status": e.status, "type": e.experiment_type,
                                "is_demo": e.is_demo, "created_at": e.created_at} for e in recent_exp],
        "activity": [{"id": a.id, "entity_type": a.entity_type, "entity_id": a.entity_id, "action": a.action, "summary": a.summary,
                      "created_at": a.created_at} for a in activity],
    }
