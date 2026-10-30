"""Stateless analysis (shared by the local API and the in-browser Pyodide engine) and the browser bundle's contents."""
import json
import re
import zipfile
from pathlib import Path

import pytest

from app import browser_engine
from app.services import quick
from app.services.electrochemistry import synthetic as ES
from app.services.wettability.synthetic import encode_png, synthetic_drop

ROOT = Path(__file__).resolve().parents[2]
PDP_META = {"method": "pdp", "mapping": {"time": "T", "potential": "Vf", "current": "Im"}, "units": {"time": "s", "potential": "V", "current": "A"}, "exposed_area_cm2": 1.0}


def test_dispatch_wettability_and_classification():
    img, _ = synthetic_drop(112)
    out = json.loads(browser_engine.dispatch("wettability_analyze", json.dumps({"params": {}}), encode_png(img)))
    assert out["ok"] and out["result"]["classification"]["label"] == "hydrophobic"
    assert out["result"]["mean_deg"] == pytest.approx(112, abs=1.5) and out["result"]["overlay_png_base64"]
    img, _ = synthetic_drop(65)
    out = json.loads(browser_engine.dispatch("wettability_analyze", "{}", encode_png(img)))
    assert out["result"]["classification"]["label"] == "hydrophilic"


def test_dispatch_corrosion_quick_matches_known_parameters():
    data = ES.pdp_tsv()
    args = {"meta": PDP_META, "params": {"anodic_mV": [80, 250], "cathodic_mV": [80, 250]}, "material": {"profile": "Fe"}}
    out = json.loads(browser_engine.dispatch("corrosion_quick", json.dumps(args), data))
    m = {x["name"]: x for x in out["result"]["analysis"]["metrics"]}
    assert out["ok"] and out["result"]["analysis"]["status"] == "ok"
    assert m["i_corr"]["value"] == pytest.approx(5.0, rel=0.05) and m["beta_a"]["value"] == pytest.approx(60, rel=0.03)
    assert m["corrosion_rate"]["parameters"]["material_source"] and out["result"]["run"]["data"]["log10_abs_current_density"]


def test_dispatch_refuses_without_units_or_with_unknown_inputs():
    bad = {"meta": {**PDP_META, "units": {"time": "s", "potential": "V", "current": None}}}
    out = json.loads(browser_engine.dispatch("corrosion_quick", json.dumps(bad), ES.pdp_tsv()))
    assert not out["ok"] and out["status"] == 422 and "unit" in out["detail"].lower()
    assert json.loads(browser_engine.dispatch("nope"))["status"] == 404
    assert not json.loads(browser_engine.dispatch("wettability_analyze", "{}", b"not an image"))["result"]["status"] == "ok"
    assert quick.resolve_material({"profile": "Fe"})["density_g_cm3"] == 7.874
    with pytest.raises(quick.QuickError):
        quick.resolve_material({"profile": "Unobtainium"})


def test_quick_endpoint_matches_engine(client):
    r = client.post("/api/corrosion/quick", files={"file": ("p.txt", ES.pdp_tsv(), "text/plain")},
                    data={"meta": json.dumps({**PDP_META, "specimen_id": 1}), "params": json.dumps({"anodic_mV": [80, 250], "cathodic_mV": [80, 250]})})
    assert r.status_code == 200, r.text
    assert r.json()["analysis"]["status"] == "ok" and client.get("/api/specimens").json()["total"] == 0  # nothing stored
    bad = client.post("/api/corrosion/quick", files={"file": ("p.txt", ES.pdp_tsv(), "text/plain")},
                      data={"meta": json.dumps({**PDP_META, "specimen_id": 1, "units": {"time": "s", "potential": "V"}})})
    assert bad.status_code == 422


def test_browser_bundle_is_in_sync_and_server_free():
    zpath = ROOT / "frontend" / "public" / "engine" / "app.zip"
    assert zpath.exists(), "run scripts/build_engine_bundle.py"
    with zipfile.ZipFile(zpath) as z:
        for name in z.namelist():
            assert z.read(name) == (ROOT / "backend" / name).read_bytes(), f"{name} differs from backend source: rebuild the bundle"
            src = z.read(name).decode()
            assert not re.search(r"^\s*(from|import)\s+(fastapi|sqlalchemy|starlette|uvicorn|app\.api|app\.database|app\.core\.config)\b", src, re.M), f"{name} imports server-only code"
