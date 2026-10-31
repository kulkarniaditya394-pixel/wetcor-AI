"""Imperfect images with known angles, and published angles from real photographs."""
import json
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_contact_angle import encode, scene  # noqa: E402

from app.services.wettability.detection import analyze  # noqa: E402

CASES = {
    "steel plate": dict(surface="steel"),
    "rough surface": dict(surface="rough"),
    "tilted": dict(tilt=-15),
    "vignette": dict(bg="vignette"),
    "reflection": dict(surface="steel", reflect=True),
    "needle": dict(needle=True),
    "overlay text": dict(text=True),
    "blur": dict(blur=3.0),
    "noise": dict(noise=18),
    "low resolution": dict(scale=0.25),
    "gravity": dict(bond=0.6, r=230),
}


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("theta", [60, 110])
def test_imperfect_scene(name, theta):
    r = analyze(encode(scene(theta, **CASES[name]), None))
    assert r["mean_deg"] == pytest.approx(theta, abs=4.0), (r["errors"], r["detection"])


def test_phone_photo_on_its_side_is_honoured_through_exif():
    import cv2
    import numpy as np

    img = np.rot90(scene(110, surface="steel")).copy()
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    data = buf.tobytes()
    # minimal EXIF APP1 block with Orientation = 6 (rotate 90 degrees clockwise to view)
    exif = b"Exif\x00\x00II*\x00\x08\x00\x00\x00\x01\x00\x12\x01\x03\x00\x01\x00\x00\x00\x06\x00\x00\x00\x00\x00\x00\x00"
    app1 = b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif
    r = analyze(data[:2] + app1 + data[2:])
    assert r["mean_deg"] == pytest.approx(110, abs=4.0)


def test_extrapolated_or_unclear_results_are_not_called_high():
    r = analyze(encode(scene(110, drop="lens", bg="colour", surface="rough"), None))
    assert r["status"] in ("ok", "needs_correction")
    assert r["uncertainty_note"]


def test_published_photographs_of_transparent_drops():
    folder = ROOT / "data" / "validation"
    labels = {i["file"]: i["label_deg"] for i in json.loads((folder / "labels.json").read_text(encoding="utf-8"))}
    r = analyze((folder / "sand_drop_129.jpg").read_bytes())
    assert r["mean_deg"] == pytest.approx(labels["sand_drop_129.jpg"], abs=3.0)
    assert r["classification"]["label"] == "hydrophobic"
    r = analyze((folder / "theta_goniometer_115.png").read_bytes())
    assert r["mean_deg"] == pytest.approx(labels["theta_goniometer_115.png"], abs=5.0)
