"""DEMO - SYNTHETIC DATA workspace. Loaded only on explicit user action; every record is flagged is_demo.

Corrosion parameters are drawn independently of the synthetic contact angles, so the demo cannot
manufacture a favourable wettability-corrosion relationship. It tests the software, nothing else.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import defaults as D
from app.core.serial import clean
from app.database.models import (AppSetting, Artifact, AuditEvent, ContactAngleRun, CorrosionAnalysis, CorrosionRun, DerivedMetric,
                                 Experiment, MLRun, Specimen, utcnow)
from app.services.electrochemistry import analysis as A
from app.services.electrochemistry import materials as MAT
from app.services.electrochemistry import synthetic as ES
from app.services.electrochemistry.parser import parse_table, suggest_mapping
from app.services.storage import audit, delete_file, store_artifact
from app.services.wettability.detection import analyze as analyze_ca
from app.services.wettability.overlay import render_overlay
from app.services.wettability.synthetic import encode_png, synthetic_drop

DEMO_TAG = "DEMO - SYNTHETIC DATA"
MATERIALS = [("Mild steel (demo)", "Fe"), ("Aluminium (demo)", "Al"), ("Copper (demo)", "Cu"), ("Zinc-coated steel (demo)", None)]
PREPS = ["As received", "Polished 1200 grit", "Grit blasted", "Silane coated"]


def _limits(db: Session) -> dict:
    row = db.get(AppSetting, "analysis")
    return D.merge(row.value if row else None)


def demo_status(db: Session) -> dict:
    return {"specimens": len(db.scalars(select(Specimen.id).where(Specimen.is_demo.is_(True))).all()),
            "contact_angle_runs": len(db.scalars(select(ContactAngleRun.id).where(ContactAngleRun.is_demo.is_(True))).all()),
            "corrosion_runs": len(db.scalars(select(CorrosionRun.id).where(CorrosionRun.is_demo.is_(True))).all()),
            "workspace_loaded": db.scalar(select(Specimen.id).where(Specimen.code == "DEMO-S01")) is not None}


DIAG_KEYS = ("status", "diagnostics", "methods", "geometry", "limits", "params", "lr_diff_deg", "classification", "errors", "uncertainty_note", "fit_method", "image")


def add_ca_run(db: Session, data: bytes, filename: str, params: dict, lim: dict, spec: Specimen, exp: Experiment, notes: str,
               subdir: str = "demo/images", **fields) -> ContactAngleRun:
    """Analyse an image exactly as the save endpoint does and store it as a demo-flagged run (automatic result kept if corrected)."""
    res = clean(analyze_ca(data, params, lim["wettability"]))
    auto = clean(analyze_ca(data, {k: v for k, v in params.items() if k == "roi"}, lim["wettability"])) if res.get("manual_correction") else None
    raw = store_artifact(db, data, kind="raw_image", subdir=subdir, original_filename=filename, content_type="image/png",
                         specimen_id=spec.id, experiment_id=exp.id, is_demo=True)
    ov = store_artifact(db, render_overlay(data, res), kind="overlay_image", subdir="demo/overlays", original_filename=f"overlay_{raw.sha256[:12]}.png",
                        content_type="image/png", specimen_id=spec.id, experiment_id=exp.id, is_demo=True)
    run = ContactAngleRun(specimen_id=spec.id, experiment_id=exp.id, image_artifact_id=raw.id, overlay_artifact_id=ov.id, method=res["method"] or "auto_failed",
                          status="accepted" if res["mean_deg"] is not None else "rejected", left_deg=res["left_deg"], right_deg=res["right_deg"],
                          mean_deg=res["mean_deg"], classification=(res["classification"] or {}).get("label"), analysis_params=params,
                          diagnostics={k: res.get(k) for k in DIAG_KEYS}, warnings=res["warnings"], auto_result=auto, algorithm_version=res["algorithm_version"],
                          notes=notes, is_demo=True, rejection_reason=None if res["mean_deg"] is not None else "automatic analysis failed", **fields)
    db.add(run)
    db.flush()
    return run


def add_corrosion_run(db: Session, data: bytes, name: str, method: str, spec: Specimen, exp: Experiment, lim: dict, params: dict,
                      material: dict | None, notes: str, mapping: dict | None = None, units: dict | None = None) -> CorrosionRun:
    """Import + analyse a synthetic file through the same code paths as the API, flagged as demo."""
    from app.api.corrosion import _store_run  # local import avoids a router import cycle
    from app.schemas.models import ImportMeta

    t = parse_table(data)
    s = suggest_mapping(t.columns, t.units_row, t.data)
    meta = ImportMeta(method=method, mapping=mapping or s["mapping"], units=units or s["units"], imag_convention=s["imag_convention"], specimen_id=spec.id,
                      experiment_id=exp.id, exposed_area_cm2=spec.exposed_area_cm2, area_source="specimen record", reference_electrode=exp.reference_electrode, notes=notes)
    df, warnings = A.build_dataset(t, method, meta.mapping, meta.units, imag_convention=meta.imag_convention, area_cm2=spec.exposed_area_cm2)
    run = db.get(CorrosionRun, _store_run(db, data, name, t, df, warnings, meta, spec, exp, spec.exposed_area_cm2, "specimen record", is_demo=True)["id"])
    res = clean(A.analyze(method, df, params, lim["electrochemistry"], area_cm2=spec.exposed_area_cm2, reference_electrode=exp.reference_electrode, material=material))
    rec = CorrosionAnalysis(corrosion_run_id=run.id, method=method, method_version=res["method_version"], params=params,
                            result={k: v for k, v in res.items() if k != "metrics"}, status=res["status"])
    db.add(rec)
    db.flush()
    for mt in res["metrics"]:
        db.add(DerivedMetric(corrosion_run_id=run.id, analysis_id=rec.id, method_version=res["method_version"], **mt))
    run.analysis_status = {"ok": "analysed", "limited": "analysis_limited", "invalid": "analysis_invalid"}[res["status"]]
    return run


def load_demo(db: Session, n_specimens: int = 10, seed: int = 7) -> dict:
    if db.scalar(select(Specimen.id).where(Specimen.code == "DEMO-S01")):
        raise ValueError("Demo workspace already loaded. Reset it first.")
    rng = np.random.default_rng(seed)
    lim = _limits(db)
    for k in range(n_specimens):
        material, profile = MATERIALS[k % len(MATERIALS)]
        prep = PREPS[(k // 2) % len(PREPS)]
        spec = Specimen(code=f"DEMO-S{k + 1:02d}", material=material, surface_preparation=prep, dimensions="50 x 25 x 2 mm (synthetic)",
                        exposed_area_cm2=1.0, roughness_ra_um=round(float(rng.uniform(0.05, 3.0)), 2), notes=DEMO_TAG, is_demo=True)
        db.add(spec)
        db.flush()
        exp = Experiment(code=f"DEMO-E{k + 1:02d}", specimen_id=spec.id, experiment_type="combined", electrolyte="NaCl", concentration_value=3.5,
                         concentration_unit="wt%", temperature_c=round(float(rng.uniform(22, 30)), 1), instrument="Synthetic generator",
                         reference_electrode="SCE", status="complete", notes=DEMO_TAG, is_demo=True, performed_at=utcnow())
        db.add(exp)
        db.flush()
        theta = float(rng.uniform(45, 135))
        for rep in range(2):
            img, _ = synthetic_drop(theta + float(rng.normal(0, 2)), size=(640, 480), radius_px=float(rng.uniform(110, 150)), seed=int(rng.integers(1e6)))
            add_ca_run(db, encode_png(img), f"DEMO_SYNTHETIC_{spec.code}_{rep + 1}.png", {}, lim, spec, exp, DEMO_TAG)
        icorr = float(10 ** rng.uniform(np.log10(0.5e-6), np.log10(20e-6)))  # independent of theta by construction
        files = [("pdp", ES.pdp_tsv(e_corr=float(rng.uniform(-0.75, -0.55)), icorr=icorr, beta_a=float(rng.uniform(0.05, 0.09)),
                                    beta_c=float(rng.uniform(0.10, 0.16)), seed=int(rng.integers(1e6))), f"DEMO_SYNTHETIC_{spec.code}_pdp.txt")]
        if k == 0:
            files += [("ocp", ES.ocp_csv(), f"DEMO_SYNTHETIC_{spec.code}_ocp.csv"), ("lpr", ES.lpr_csv(icorr=icorr), f"DEMO_SYNTHETIC_{spec.code}_lpr.csv"),
                      ("eis", ES.eis_semicolon(), f"DEMO_SYNTHETIC_{spec.code}_eis.csv")]
        for method, data, name in files:
            params = {"anodic_mV": [70, 220], "cathodic_mV": [70, 220]} if method == "pdp" else {}
            material = {**MAT.profile(profile), "is_alloy": False} if profile else None
            add_corrosion_run(db, data, name, method, spec, exp, lim, params, material, DEMO_TAG)
    audit(db, "demo", "workspace", "load", f"{DEMO_TAG}: demo workspace loaded ({n_specimens} synthetic specimens)")
    db.commit()
    return demo_status(db)


def reset_demo(db: Session, models_dir: Path) -> dict:
    before = demo_status(db)
    spec_ids = db.scalars(select(Specimen.id).where(Specimen.is_demo.is_(True))).all()
    runs = db.scalars(select(CorrosionRun).where(CorrosionRun.is_demo.is_(True))).all()
    for m in db.scalars(select(DerivedMetric).where(DerivedMetric.corrosion_run_id.in_([r.id for r in runs]))).all():
        db.delete(m)
    db.flush()
    for a in db.scalars(select(CorrosionAnalysis).where(CorrosionAnalysis.corrosion_run_id.in_([r.id for r in runs]))).all():
        db.delete(a)
    db.flush()
    for r in runs:
        db.delete(r)
    for c in db.scalars(select(ContactAngleRun).where(ContactAngleRun.is_demo.is_(True))).all():
        db.delete(c)
    db.flush()
    for a in db.scalars(select(Artifact).where(Artifact.is_demo.is_(True))).all():
        delete_file(a)
        db.delete(a)
    db.flush()
    for e in db.scalars(select(Experiment).where(Experiment.is_demo.is_(True))).all():
        db.delete(e)
    db.flush()
    for s in db.scalars(select(Specimen).where(Specimen.id.in_(spec_ids))).all():
        db.delete(s)
    for run in db.scalars(select(MLRun).where(MLRun.includes_demo.is_(True))).all():
        if run.model_path:
            (models_dir / run.model_path).unlink(missing_ok=True)
        db.delete(run)
    db.query(AuditEvent).filter(AuditEvent.entity_type == "demo").delete()
    audit(db, "demo", "workspace", "reset", f"{DEMO_TAG}: demo workspace removed ({before['specimens']} specimens)")
    db.commit()
    return {"removed": before}
