"""Contact-angle geometry and pipeline tests on SYNTHETIC images with angles known by construction.

Tolerances below reflect rasterisation + fitting on clean synthetic silhouettes only. They are not
a statement of real-world metrology accuracy.
"""
import hashlib

import numpy as np
import pytest

from app.services.wettability import geometry as g
from app.services.wettability.detection import analyze
from app.services.wettability.overlay import render_overlay
from app.services.wettability.synthetic import encode_png, synthetic_drop

TOL = 1.5  # deg, synthetic geometry tolerance


def run(theta_l, theta_r=None, params=None, **kw):
    img, truth = synthetic_drop(theta_l, theta_r, **kw)
    return analyze(encode_png(img), params or {}), truth


# ---------- pure geometry ----------

def test_tangent_angle_sides_not_reversed():
    # Tangent leaning inward (towards drop centre) means theta < 90 on both sides.
    assert g.tangent_angle_deg(np.array([1.0, 1.0]), "left") == pytest.approx(45)
    assert g.tangent_angle_deg(np.array([-1.0, 1.0]), "right") == pytest.approx(45)
    assert g.tangent_angle_deg(np.array([-1.0, 1.0]), "left") == pytest.approx(135)
    assert g.tangent_angle_deg(np.array([1.0, 1.0]), "right") == pytest.approx(135)
    with pytest.raises(g.GeometryError):
        g.tangent_angle_deg(np.array([1.0, -0.5]), "left")


def test_frame_handles_image_y_down_and_tilt():
    f = g.make_frame((0, 100), (100, 100))
    assert f.to_uv([[50, 90]])[0].tolist() == pytest.approx([50, 10])  # 10 px ABOVE baseline -> v = +10
    t = g.make_frame((0, 0), (100, 10))
    assert t.tilt_deg == pytest.approx(np.degrees(np.arctan2(10, 100)))
    assert g.make_frame((100, 10), (0, 0)).d[0] > 0  # point order does not matter


def test_circle_fit_analytic():
    r, vc = 100.0, -50.0  # centre below baseline -> theta = arccos(0.5) = 60
    ang = np.linspace(0.6, np.pi - 0.6, 80)
    pts = np.column_stack([r * np.cos(ang), vc + r * np.sin(ang)])
    cf = g.fit_circle(pts)
    assert cf.r == pytest.approx(r, abs=1e-6) and cf.vc == pytest.approx(vc, abs=1e-6)
    assert cf.angle_deg() == pytest.approx(60, abs=1e-6)


def test_manual_tangent_angle_with_tilted_baseline():
    f = g.make_frame((0, 0), (200, 20))
    theta = np.radians(70)
    c = f.to_xy([[20, 0]])[0]
    tl = f.to_xy([[20 + 50 * np.cos(theta), 50 * np.sin(theta)]])[0]
    assert g.manual_tangent_angle(f, c, tl, "left") == pytest.approx(70)
    cr = f.to_xy([[180, 0]])[0]
    tr = f.to_xy([[180 - 50 * np.cos(np.radians(110)), 50 * np.sin(np.radians(110))]])[0]
    assert g.manual_tangent_angle(f, cr, tr, "right") == pytest.approx(110)


@pytest.mark.parametrize("value,label", [(45.0, "hydrophilic"), (89.9, "hydrophilic"), (90.0, "boundary"),
                                         (90.04, "boundary"), (90.1, "hydrophobic"), (140.0, "hydrophobic")])
def test_classification_at_90(value, label):
    assert g.classify(value)["label"] == label


def test_classification_uncertainty_flags():
    assert g.classify(89.0, tolerance_deg=2.0)["recommend_repeat"] is True
    assert g.classify(60.0, tolerance_deg=2.0)["recommend_repeat"] is False
    straddle = g.classify(80.0, 70.0, 95.0, tolerance_deg=2.0)
    assert straddle["uncertain"] and any("opposite sides" in r for r in straddle["reasons"])
    assert g.classify(90.0)["text"] == "At hydrophilic/hydrophobic boundary"
    assert g.classify(None) is None


# ---------- full pipeline ----------

@pytest.mark.parametrize("theta,kw", [(20, dict(radius_px=600, size=(1280, 480))), (30, dict(radius_px=380)),
                                      (60, {}), (120, {}), (150, dict(radius_px=110, baseline_y=380))])
def test_known_angles(theta, kw):
    r, _ = run(theta, **kw)
    assert r["status"] == "ok", r["errors"]
    assert r["left_deg"] == pytest.approx(theta, abs=TOL)
    assert r["right_deg"] == pytest.approx(theta, abs=TOL)
    assert r["methods"]["circle"]["angle_deg"] == pytest.approx(theta, abs=TOL)
    assert 0 < r["left_deg"] < 180 and 0 < r["right_deg"] < 180
    assert r["classification"]["label"] == ("hydrophilic" if theta < 90 else "hydrophobic")


def test_near_90_recommends_repeat():
    r, _ = run(90)
    assert r["mean_deg"] == pytest.approx(90, abs=TOL)
    assert r["classification"]["recommend_repeat"] is True


def test_asymmetric_left_right_not_reversed():
    r, _ = run(70, 100)
    assert r["left_deg"] == pytest.approx(70, abs=TOL)
    assert r["right_deg"] == pytest.approx(100, abs=TOL)
    lr = next(d for d in r["diagnostics"] if d["key"] == "lr_diff")
    assert lr["status"] == "fail" and r["status"] == "needs_correction"


@pytest.mark.parametrize("tilt,theta", [(6, 80), (-8, 110)])
def test_tilted_baseline(tilt, theta):
    r, truth = run(theta, tilt_deg=tilt)
    assert r["geometry"]["tilt_deg"] == pytest.approx(tilt, abs=0.3)
    assert r["mean_deg"] == pytest.approx(theta, abs=TOL)


def test_low_contrast_warns_but_measures():
    r, _ = run(75, background=120, foreground=100)
    assert any("Low contrast" in w for w in r["warnings"])
    assert r["mean_deg"] == pytest.approx(75, abs=2.0)


def test_very_low_contrast_refuses_and_manual_tangent_recovers():
    img, truth = synthetic_drop(65, background=120, foreground=114, noise_sigma=2)
    data = encode_png(img)
    auto = analyze(data)
    assert auto["status"] == "failed" and auto["mean_deg"] is None
    f = g.make_frame(*truth["baseline"])
    th = np.radians(65)
    cl, cr = f.to_uv([truth["contact_left"]])[0], f.to_uv([truth["contact_right"]])[0]
    manual = analyze(data, {
        "mode": "manual_tangent", "baseline": truth["baseline"],
        "contact_left": truth["contact_left"], "contact_right": truth["contact_right"],
        "tangent_left": f.to_xy([[cl[0] + 40 * np.cos(th), 40 * np.sin(th)]])[0].tolist(),
        "tangent_right": f.to_xy([[cr[0] - 40 * np.cos(th), 40 * np.sin(th)]])[0].tolist(),
    })
    assert manual["method"] == "manual_tangent" and manual["manual_correction"] is True
    assert manual["mean_deg"] == pytest.approx(65, abs=0.01)


def test_clipped_droplet_fails():
    r, truth = run(110, centre_x=60)
    assert r["status"] == "failed" and r["mean_deg"] is None
    img, truth = synthetic_drop(110, centre_x=60, substrate=False)
    r = analyze(encode_png(img), {"baseline": truth["baseline"]})
    assert r["status"] == "failed" and r["mean_deg"] is None
    assert any("clipped" in e for e in r["errors"])


def test_no_droplet_fails():
    img, _ = synthetic_drop(60, radius_px=0.01)
    r = analyze(encode_png(img))
    assert r["status"] == "failed" and r["mean_deg"] is None


def test_insufficient_contour_points_fails():
    r, _ = run(60, radius_px=9)
    assert r["status"] == "failed" and r["mean_deg"] is None


def test_floating_object_without_baseline_requests_manual_baseline():
    r, _ = run(100, substrate=False)
    assert r["status"] == "failed"
    assert any("baseline" in e.lower() for e in r["errors"])


def test_manual_baseline_is_recorded_as_correction():
    img, truth = synthetic_drop(100, substrate=False)
    r = analyze(encode_png(img), {"baseline": truth["baseline"]})
    assert r["method"] == "manual_corrected" and r["manual_correction"] is True
    assert r["mean_deg"] == pytest.approx(100, abs=TOL)


def test_corrupt_image():
    r = analyze(b"not an image")
    assert r["status"] == "failed" and r["mean_deg"] is None


def test_original_bytes_unmodified_and_no_invented_uncertainty():
    img, _ = synthetic_drop(80)
    data = encode_png(img)
    before = hashlib.sha256(data).hexdigest()
    r = analyze(data)
    overlay = render_overlay(data, r)
    assert hashlib.sha256(data).hexdigest() == before
    assert overlay != data and overlay[:4] == b"\x89PNG"
    flat = str(r).lower()
    assert "confidence" not in flat and "uncertainty_deg" not in flat
    assert "not a calibrated" in r["uncertainty_note"]
