"""Builds the modelling table from linked database records (one row per corrosion run with a valid target)."""
from __future__ import annotations

import statistics

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ContactAngleRun, CorrosionRun, DerivedMetric, Experiment, Specimen
from app.services.machine_learning.core import TARGETS


def build_rows(db: Session, target: str, data_source: str = "real") -> tuple[list[dict], list[dict]]:
    """Return (rows, excluded). Real and demo data are never mixed."""
    demo = data_source == "demo"
    metric = TARGETS[target]["metric"]
    q = (select(DerivedMetric, CorrosionRun, Specimen)
         .join(CorrosionRun, CorrosionRun.id == DerivedMetric.corrosion_run_id)
         .join(Specimen, Specimen.id == CorrosionRun.specimen_id)
         .where(DerivedMetric.name == metric, DerivedMetric.superseded.is_(False), CorrosionRun.is_demo.is_(demo))
         .order_by(CorrosionRun.id))
    rows, excluded = [], []
    ca_cache: dict[int, list[ContactAngleRun]] = {}
    for m, run, spec in db.execute(q).all():
        if not m.valid or m.value is None:
            excluded.append({"run_id": run.id, "specimen_code": spec.code, "reason": "result flagged invalid/unreliable by its analysis"})
            continue
        if m.parameters.get("selection") == "auto_proposed":
            excluded.append({"run_id": run.id, "specimen_code": spec.code, "reason": "Tafel regions auto-proposed but not confirmed by the user"})
            continue
        if spec.id not in ca_cache:
            ca_cache[spec.id] = db.scalars(select(ContactAngleRun).where(ContactAngleRun.specimen_id == spec.id, ContactAngleRun.status == "accepted",
                                                                         ContactAngleRun.mean_deg.is_not(None))).all()
        cas = ca_cache[spec.id]
        same_exp = [c for c in cas if run.experiment_id and c.experiment_id == run.experiment_id]
        used = same_exp or cas
        exp = db.get(Experiment, run.experiment_id) if run.experiment_id else None
        angles = [c.mean_deg for c in used]
        rows.append({
            "run_id": run.id, "specimen_code": spec.code, "is_demo": run.is_demo, "target": float(m.value),
            "material": spec.material, "surface_preparation": spec.surface_preparation, "roughness_ra_um": spec.roughness_ra_um,
            "electrolyte": exp.electrolyte if exp else None, "concentration_value": exp.concentration_value if exp else None,
            "concentration_unit": exp.concentration_unit if exp else None, "temperature_c": exp.temperature_c if exp else None,
            "contact_angle_deg": statistics.fmean(angles) if angles else None, "contact_angle_n": len(angles),
            "contact_angle_link": "same experiment" if same_exp else "same specimen" if cas else None,
            "metric_id": m.id,
        })
    return rows, excluded
