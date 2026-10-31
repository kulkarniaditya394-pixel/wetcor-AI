"""End-to-end API flows on SYNTHETIC fixtures: specimen -> contact angle -> corrosion -> dataset -> ML -> export."""
import csv
import hashlib
import io
import json

import pytest

from app.core.config import settings
from app.services.electrochemistry import synthetic as ES
from app.services.wettability.synthetic import encode_png, synthetic_drop


def make_specimen(client, code="S-01", **kw):
    r = client.post("/api/specimens", json={"code": code, "material": "Mild steel", "surface_preparation": "Polished", "exposed_area_cm2": 1.0, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def make_experiment(client, spec_id, code="E-01"):
    r = client.post("/api/experiments", json={"code": code, "specimen_id": spec_id, "electrolyte": "NaCl", "concentration_value": 3.5,
                                              "concentration_unit": "wt%", "temperature_c": 25, "reference_electrode": "SCE"})
    assert r.status_code == 201, r.text
    return r.json()


def drop_png(theta=70, **kw):
    img, truth = synthetic_drop(theta, **kw)
    return encode_png(img), truth


def save_ca(client, spec_id, exp_id=None, theta=70, params=None, status="accepted", reason=None):
    data, _ = drop_png(theta)
    meta = {"specimen_id": spec_id, "experiment_id": exp_id, "status": status, "rejection_reason": reason}
    return client.post("/api/wettability/measurements", files={"image": ("capture.png", data, "image/png")},
                       data={"params": json.dumps(params or {}), "meta": json.dumps(meta)}), data


def import_pdp(client, spec_id, exp_id=None, filename="pdp.txt", **kw):
    data = ES.pdp_tsv(**kw)
    meta = {"method": "pdp", "mapping": {"potential": "Vf", "current": "Im"}, "units": {"potential": "V", "current": "A"},
            "specimen_id": spec_id, "experiment_id": exp_id}
    r = client.post("/api/corrosion/import", files={"file": (filename, data, "text/plain")}, data={"meta": json.dumps(meta)})
    return r, data


def test_health_and_version(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["database"] == "ok" and h["schema_version"] >= 1
    assert client.get("/api/version").json()["contact_angle_algorithm"].startswith("ca-")


def test_specimen_crud_validation_and_search(client):
    s = make_specimen(client)
    assert client.post("/api/specimens", json={"code": "S-01", "material": "x"}).status_code == 409
    assert client.post("/api/specimens", json={"code": "DEMO-9", "material": "x"}).status_code == 422
    assert client.post("/api/specimens", json={"code": "bad id!", "material": "x"}).status_code == 422
    assert client.post("/api/specimens", json={"code": "S-02", "material": "x", "exposed_area_cm2": -1}).status_code == 422
    make_specimen(client, "S-02", material="Aluminium")
    r = client.patch(f"/api/specimens/{s['id']}", json={"roughness_ra_um": 0.4})
    assert r.json()["roughness_ra_um"] == 0.4
    detail = client.get(f"/api/specimens/{s['id']}").json()
    assert any(h["action"] == "update" for h in detail["history"])
    page = client.get("/api/specimens", params={"q": "alumin"}).json()
    assert page["total"] == 1 and page["items"][0]["code"] == "S-02"
    page = client.get("/api/specimens", params={"sort": "code", "page_size": 1, "page": 2}).json()
    assert page["total"] == 2 and page["items"][0]["code"] == "S-02"


def test_experiment_must_match_specimen(client):
    s1, s2 = make_specimen(client), make_specimen(client, "S-02")
    e1 = make_experiment(client, s1["id"])
    r, _ = save_ca(client, s2["id"], e1["id"])
    assert r.status_code == 422 and "different specimen" in r.text


def test_contact_angle_flow_with_correction_history(client):
    s = make_specimen(client)
    e = make_experiment(client, s["id"])
    data, truth = drop_png(70)
    r = client.post("/api/wettability/analyze", files={"image": ("c.png", data, "image/png")}, data={"params": "{}"})
    res = r.json()
    assert res["status"] == "ok" and abs(res["mean_deg"] - 70) < 1.5 and res["overlay_png_base64"]
    r, data = save_ca(client, s["id"], e["id"], 70)
    run = r.json()
    assert run["method"] == "auto_polynomial" and run["auto_result"] is None and run["classification"] == "hydrophilic"
    detail = client.get(f"/api/wettability/measurements/{run['id']}").json()
    assert detail["image"]["sha256"] == hashlib.sha256(data).hexdigest() and detail["image"]["integrity"] == "ok"
    raw = client.get(f"/api/artifacts/{run['image_artifact_id']}/download").content
    assert raw == data  # original preserved byte-for-byte
    assert run["overlay_artifact_id"] != run["image_artifact_id"]
    # manual correction on save -> manual_corrected + automatic result kept separately
    r, _ = save_ca(client, s["id"], e["id"], 70, params={"baseline": truth["baseline"]})
    corrected = r.json()
    assert corrected["method"] == "manual_corrected" and corrected["auto_result"]["mean_deg"] is not None
    # re-analysis via PATCH keeps previous values in history
    r = client.patch(f"/api/wettability/measurements/{run['id']}", json={"reanalyse_params": {"primary_method": "circle"}, "reason": "compare"})
    assert r.status_code == 200 and r.json()["method"] == "auto_circle"
    hist = client.get(f"/api/wettability/measurements/{run['id']}").json()["history"]
    re = next(h for h in hist if h["action"] == "reanalysis")
    assert re["details"]["previous"]["method"] == "auto_polynomial"
    assert r.json()["auto_result"]["method"] == "auto_polynomial"


def test_failed_analysis_cannot_be_accepted_but_can_be_rejected(client):
    s = make_specimen(client)
    img, _ = synthetic_drop(60, background=120, foreground=120, noise_sigma=3)
    data = encode_png(img)
    meta = {"specimen_id": s["id"], "status": "accepted"}
    r = client.post("/api/wettability/measurements", files={"image": ("c.png", data, "image/png")}, data={"meta": json.dumps(meta)})
    assert r.status_code == 422
    meta = {"specimen_id": s["id"], "status": "rejected"}
    assert client.post("/api/wettability/measurements", files={"image": ("c.png", data, "image/png")}, data={"meta": json.dumps(meta)}).status_code == 422
    meta["rejection_reason"] = "poor contrast"
    r = client.post("/api/wettability/measurements", files={"image": ("c.png", data, "image/png")}, data={"meta": json.dumps(meta)})
    assert r.status_code == 201 and r.json()["mean_deg"] is None and r.json()["status"] == "rejected"


def test_corrosion_import_analyse_reanalyse(client):
    s = make_specimen(client)
    e = make_experiment(client, s["id"])
    data = ES.pdp_tsv()
    pv = client.post("/api/corrosion/import/preview", files={"file": ("pdp.txt", data, "text/plain")}).json()
    assert pv["suggestion"]["mapping"]["potential"] == "Vf" and pv["suggestion"]["units"]["current"] == "A"
    # units must be explicit
    bad = {"method": "pdp", "mapping": {"potential": "Vf", "current": "Im"}, "units": {"potential": "V", "current": None}, "specimen_id": s["id"]}
    assert client.post("/api/corrosion/import", files={"file": ("pdp.txt", data, "text/plain")}, data={"meta": json.dumps(bad)}).status_code == 422
    r, data = import_pdp(client, s["id"], e["id"])
    run = r.json()
    assert run["area_source"] == "specimen record" and run["n_points"] > 500
    raw = client.get(f"/api/artifacts/{run['raw_artifact_id']}/download")
    assert raw.content == data and raw.headers["x-content-sha256"] == hashlib.sha256(data).hexdigest()
    a1 = client.post(f"/api/corrosion/runs/{run['id']}/analyze", json={"params": {}}).json()
    assert a1["status"] == "limited" and a1["fit"]["selection"] == "auto_proposed"
    a2 = client.post(f"/api/corrosion/runs/{run['id']}/analyze", json={"params": {"anodic_mV": [80, 250], "cathodic_mV": [80, 250]},
                                                                      "material": {"profile": "Fe"}}).json()
    assert a2["status"] == "ok"
    metrics = {m["name"]: m for m in client.get(f"/api/corrosion/runs/{run['id']}/metrics").json()}
    assert abs(metrics["i_corr"]["value"] - 5.0) / 5 < 0.05 and metrics["corrosion_rate"]["parameters"]["material_source"]
    allm = client.get(f"/api/corrosion/runs/{run['id']}/metrics", params={"include_superseded": True}).json()
    assert any(m["superseded"] for m in allm)
    detail = client.get(f"/api/corrosion/runs/{run['id']}").json()
    assert len(detail["analyses"]) == 2 and sum(not a["superseded"] for a in detail["analyses"]) == 1
    d = client.get(f"/api/corrosion/runs/{run['id']}/data").json()
    assert "log10_abs_current_density" in d["data"] and d["data"]["potential_V"][0] < 0


def test_ocp_import_never_yields_corrosion_rate(client):
    s = make_specimen(client)
    meta = {"method": "ocp", "mapping": {"time": "Time (s)", "potential": "Potential (V vs SCE)"}, "units": {"time": "s", "potential": "V"},
            "specimen_id": s["id"], "reference_electrode": "SCE"}
    run = client.post("/api/corrosion/import", files={"file": ("ocp.csv", ES.ocp_csv(), "text/csv")}, data={"meta": json.dumps(meta)}).json()
    out = client.post(f"/api/corrosion/runs/{run['id']}/analyze", json={"params": {}, "material": {"profile": "Fe"}}).json()
    assert {m["name"] for m in out["metrics"]}.isdisjoint({"i_corr", "corrosion_rate"})


def test_unsafe_filename_is_contained(client):
    s = make_specimen(client)
    r, _ = import_pdp(client, s["id"], filename="..\\..\\..\\evil.txt")
    assert r.status_code == 201
    info = client.get(f"/api/artifacts/{r.json()['raw_artifact_id']}").json()
    stored = list((settings.data_dir / "raw" / "instrument").iterdir())
    assert len(stored) == 1 and ".." not in stored[0].name and stored[0].name.endswith("evil.txt")
    assert info["original_filename"].endswith("evil.txt")


def test_linking_dataset_and_export_match_database(client):
    s = make_specimen(client)
    e = make_experiment(client, s["id"])
    save_ca(client, s["id"], e["id"], 75)
    r, _ = import_pdp(client, s["id"], e["id"])
    client.post(f"/api/corrosion/runs/{r.json()['id']}/analyze", json={"params": {"anodic_mV": [80, 250], "cathodic_mV": [80, 250]}})
    det = client.get(f"/api/specimens/{s['id']}").json()
    assert len(det["contact_angle_runs"]) == 1 and len(det["corrosion_runs"]) == 1
    ds = client.post("/api/ml/readiness-check", json={"target": "i_corr"}).json()
    assert ds["rows"][0]["contact_angle_deg"] == pytest.approx(det["contact_angle_runs"][0]["mean_deg"])
    assert ds["rows"][0]["contact_angle_link"] == "same experiment"
    assert ds["readiness"]["can_train"] is False  # one specimen: honest refusal
    assert client.post("/api/ml/train", json={"target": "i_corr"}).status_code == 422
    rows = list(csv.DictReader(io.StringIO(client.get("/api/exports/contact_angles.csv").text)))
    assert float(rows[0]["mean_deg"]) == pytest.approx(det["contact_angle_runs"][0]["mean_deg"]) and rows[0]["specimen_code"] == "S-01"
    rep = client.get(f"/api/reports/experiment/{e['id']}")
    assert rep.status_code == 200 and "E-01" in rep.text and det["artifacts"][0]["sha256"][:16] in rep.text and "DEMO - SYNTHETIC" not in rep.text
    js = client.get(f"/api/reports/experiment/{e['id']}", params={"format": "json"}).json()
    assert js["corrosion_runs"][0]["metrics"]


def test_demo_workspace_ml_comparison_and_prediction(client):
    assert client.post("/api/demo/load").status_code == 200
    assert client.get("/api/specimens").json()["total"] == 0  # demo hidden from the real workspace
    assert client.get("/api/specimens", params={"demo_only": True}).json()["total"] == 10
    real = client.post("/api/ml/readiness-check", json={"target": "i_corr", "data_source": "real"}).json()
    assert real["readiness"]["n_records"] == 0 and not real["readiness"]["can_train"]
    ready = client.post("/api/ml/readiness-check", json={"target": "i_corr", "data_source": "demo"}).json()["readiness"]
    assert ready["can_train"] and ready["level"] == "exploratory" and not ready["validated_badge"]
    assert any("DEMO" in a for a in ready["advisories"])
    bad = client.post("/api/ml/train", json={"target": "i_corr", "data_source": "demo", "baseline_features": ["material", "rp"]})
    assert bad.status_code == 422 and "leakage" in bad.text.lower()
    out = client.post("/api/ml/train", json={"target": "i_corr", "data_source": "demo", "seed": 3}).json()
    assert len(out["runs"]) == 5 and "Exploratory" in out["interpretation"]
    comp = client.get(f"/api/ml/comparisons/{out['comparison_id']}").json()
    for run in comp["runs"]:
        groups = [g for f in run["metrics"]["folds"] for g in f["test_groups"]]
        assert len(groups) == len(set(groups)) == run["n_groups"]  # each specimen held out exactly once
    wet = next(r for r in comp["runs"] if r["feature_set"] == "wettability" and r["model_family"] == "random_forest")
    p = client.post("/api/ml/predict", json={"run_id": wet["id"], "inputs": {"material": "Unobtainium", "surface_preparation": "As received",
                                                                            "electrolyte": "NaCl", "temperature_c": 80, "contact_angle_deg": 100}}).json()
    assert p["origin"] == "predicted" and p["prediction"] > 0
    assert any("not seen in training" in w for w in p["warnings"]) and any("outside the training range" in w for w in p["warnings"])
    assert any("DEMO" in w for w in p["warnings"])
    rep = client.get(f"/api/reports/ml/{wet['id']}")
    assert "DEMO - SYNTHETIC DATA" in rep.text
    preds = list(csv.DictReader(io.StringIO(client.get("/api/exports/ml_predictions.csv", params={"comparison_id": out["comparison_id"]}).text.split("\n", 1)[1])))
    assert len(preds) == 5 * ready["n_records"]
    r = client.delete("/api/demo", params={"confirm": "RESET-DEMO"})
    assert r.status_code == 200 and client.get("/api/demo").json()["specimens"] == 0
    assert client.get("/api/ml/runs").json() == []


def test_guarded_deletion(client):
    s = make_specimen(client)
    r, _ = save_ca(client, s["id"])
    run = r.json()
    assert client.delete(f"/api/specimens/{s['id']}", params={"confirm": "S-01"}).status_code == 409
    assert client.delete(f"/api/wettability/measurements/{run['id']}", params={"confirm": "nope"}).status_code == 400
    out = client.delete(f"/api/wettability/measurements/{run['id']}", params={"confirm": f"CA-{run['id']}"}).json()
    assert out["trashed_files"] and all((settings.data_dir / t).exists() for t in out["trashed_files"])
    assert client.delete(f"/api/specimens/{s['id']}", params={"confirm": "S-01"}).status_code == 200


def test_missing_file_reference_reported(client):
    s = make_specimen(client)
    r, _ = save_ca(client, s["id"])
    run = r.json()
    for f in (settings.data_dir / "raw" / "images").iterdir():
        f.unlink()
    assert "missing" in client.get(f"/api/wettability/measurements/{run['id']}").json()["image"]["integrity"]
    assert client.get(f"/api/artifacts/{run['image_artifact_id']}/download").status_code == 409


def test_upload_limits_and_types(client):
    assert client.post("/api/corrosion/import/preview", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.post("/api/wettability/analyze", files={"image": ("x.txt", b"hello", "text/plain")}).status_code == 415
