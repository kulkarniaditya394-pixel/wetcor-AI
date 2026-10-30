"""Pre-computed showcase test, built from data/showcase/showcase.json on explicit request.

Every value is computed by the normal analysis code from the files listed in the manifest; the
manifest only supplies inputs (image, parameters, metadata) and third-party reference values.
Records are flagged is_demo because the electrochemistry is synthetic and the image is a public stand-in.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import ROOT_DIR
from app.database.models import ContactAngleRun, CorrosionRun, Experiment, Specimen, utcnow
from app.services.demo import _limits, add_ca_run, add_corrosion_run
from app.services.electrochemistry import materials as MAT
from app.services.storage import audit, store_artifact

SHOWCASE_DIR = ROOT_DIR / "data" / "showcase"


def manifest(folder: Path = SHOWCASE_DIR) -> dict:
    path = folder / "showcase.json"
    if not path.exists():
        raise FileNotFoundError("data/showcase/showcase.json is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def status(db: Session, folder: Path = SHOWCASE_DIR) -> dict | None:
    m = manifest(folder)
    spec = db.scalar(select(Specimen).where(Specimen.code == m["specimen"]["code"]))
    if spec is None:
        return None
    exp = db.scalar(select(Experiment).where(Experiment.code == m["experiment"]["code"]))
    ca = db.scalars(select(ContactAngleRun.id).where(ContactAngleRun.specimen_id == spec.id)).all()
    ec = db.scalars(select(CorrosionRun).where(CorrosionRun.specimen_id == spec.id).order_by(CorrosionRun.id)).all()
    return {"specimen_id": spec.id, "experiment_id": exp.id if exp else None, "contact_angle_run_ids": list(ca),
            "corrosion_runs": [{"id": r.id, "method": r.method} for r in ec], "manifest": m}


def load(db: Session, folder: Path = SHOWCASE_DIR) -> dict:
    m = manifest(folder)
    if db.scalar(select(Specimen.id).where(Specimen.code == m["specimen"]["code"])):
        raise ValueError("Showcase example is already loaded.")
    lim = _limits(db)
    tag = "SHOWCASE - public stand-in image + SYNTHETIC electrochemistry"
    spec = Specimen(**m["specimen"], is_demo=True)
    db.add(spec)
    db.flush()
    exp = Experiment(**m["experiment"], specimen_id=spec.id, status="complete", is_demo=True, performed_at=utcnow(), notes=tag)
    db.add(exp)
    db.flush()

    ca = m["contact_angle"]
    if ca.get("source_image"):
        store_artifact(db, (folder / ca["source_image"]).read_bytes(), kind="source_image", subdir="demo/showcase", original_filename=ca["source_image"],
                       content_type="image/png", specimen_id=spec.id, experiment_id=exp.id, is_demo=True, meta={"source": ca["source"]})
    run = add_ca_run(db, (folder / ca["image"]).read_bytes(), ca["image"], ca["params"], lim, spec, exp,
                     f"{tag}. {ca.get('correction_reason', '')}", subdir="demo/showcase", liquid=ca.get("liquid", "Deionised water"),
                     droplet_volume_ul=ca.get("droplet_volume_ul"), captured_at=utcnow())
    if run.auto_result is not None:
        audit(db, "contact_angle_run", run.id, "manual_correction",
              f"Manual correction applied: automatic {run.auto_result.get('mean_deg')} deg -> corrected {run.mean_deg} deg",
              {"reason": ca.get("correction_reason"), "params": ca["params"]})

    for r in m["corrosion_runs"]:
        material = {**MAT.profile(r["material_profile"]), "is_alloy": False} if r.get("material_profile") else None
        add_corrosion_run(db, (folder / r["file"]).read_bytes(), r["file"], r["method"], spec, exp, lim, r.get("params", {}), material,
                          tag, mapping=r.get("mapping"), units=r.get("units"))
    audit(db, "demo", "showcase", "load", f"Showcase example loaded ({spec.code})")
    db.commit()
    return status(db, folder)
