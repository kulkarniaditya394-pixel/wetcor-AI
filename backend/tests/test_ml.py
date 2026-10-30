"""ML evaluation integrity on SYNTHETIC rows (no relationship to real materials)."""
import numpy as np
import pytest
from sklearn.model_selection import GroupKFold

from app.core.defaults import defaults
from app.services.machine_learning import core as C

POLICY = defaults()["ml"]
BASE = ["material", "surface_preparation", "temperature_c"]


def rows(n_groups=8, per_group=3, seed=0, demo=False):
    rng = np.random.default_rng(seed)
    out, rid = [], 0
    for g in range(n_groups):
        mat = ["steel", "aluminium"][g % 2]
        ca = float(rng.uniform(40, 140))
        for _ in range(per_group):
            rid += 1
            out.append({"run_id": rid, "specimen_code": f"G{g}", "is_demo": demo, "material": mat, "surface_preparation": ["a", "b", "c"][g % 3],
                        "temperature_c": float(rng.uniform(20, 30)), "roughness_ra_um": None, "electrolyte": "NaCl", "concentration_value": 3.5,
                        "concentration_unit": "wt%", "contact_angle_deg": ca, "target": float(10 ** rng.uniform(-0.3, 1.3))})
    return out


def test_regression_metrics_hand_values():
    m = C.regression_metrics(np.array([1.0, 2.0, 3.0]), np.array([1.0, 2.0, 4.0]))
    assert m["mae"] == pytest.approx(1 / 3) and m["rmse"] == pytest.approx(np.sqrt(1 / 3)) and m["r2"] == pytest.approx(0.5)
    undefined = C.regression_metrics(np.array([2.0, 2.0]), np.array([1.0, 3.0]))
    assert undefined["r2"] is None and "undefined" in undefined["r2_note"]
    assert C.regression_metrics(np.array([2.0]), np.array([1.0]))["r2"] is None


@pytest.mark.parametrize("feats,msg", [(["material", "i_corr"], "leakage"), (["rp"], "leakage"), (["colour"], "not permitted"),
                                       (["contact_angle_deg"], "automatically")])
def test_request_validation_and_leakage(feats, msg):
    with pytest.raises(C.MLError, match=msg):
        C.validate_request("i_corr", feats, "log10")
    with pytest.raises(C.MLError, match="Unknown target"):
        C.validate_request("hardness", BASE, "none")


def test_readiness_levels_and_demo_flag():
    assert C.readiness(rows(3), "i_corr", BASE, POLICY)["level"] == "insufficient"
    r = C.readiness(rows(6), "i_corr", BASE, POLICY)
    assert r["level"] == "exploratory" and r["can_train"] and not r["validated_badge"]
    assert any("Repeated measurements" in a for a in r["advisories"])
    r = C.readiness(rows(16), "i_corr", BASE, POLICY)
    assert r["level"] == "adequate" and r["validated_badge"]
    r = C.readiness(rows(16, demo=True), "i_corr", BASE, POLICY)
    assert r["level"] == "exploratory" and any("DEMO" in a for a in r["advisories"])
    flat = rows(6)
    for x in flat:
        x["contact_angle_deg"] = 80.0
    assert any("does not vary" in b for b in C.readiness(flat, "i_corr", BASE, POLICY)["blocking"])


def test_grouped_split_keeps_specimens_together_and_is_reproducible(tmp_path):
    data = rows(8, per_group=4)
    a = C.train_comparison(data, "i_corr", BASE, "log10", 5, POLICY, tmp_path, "a")
    b = C.train_comparison(data, "i_corr", BASE, "log10", 5, POLICY, tmp_path, "b")
    for run_a, run_b in zip(a["runs"], b["runs"]):
        assert run_a["metrics"]["mae"] == pytest.approx(run_b["metrics"]["mae"])  # fixed seed -> identical
        held = [g for f in run_a["metrics"]["folds"] for g in f["test_groups"]]
        assert sorted(held) == sorted({r["specimen_code"] for r in data})  # every group held out exactly once
        assert all(p["predicted"] == p["predicted"] for p in run_a["oof_predictions"])  # no NaN: every record predicted out-of-fold
    names = [r["name"] for r in a["runs"]]
    assert names[0] == "Mean-only baseline" and len(names) == 5
    wet = next(r for r in a["runs"] if r["feature_set"] == "wettability")
    assert C.WETTABILITY_FEATURE in wet["features"]
    assert all(C.WETTABILITY_FEATURE not in r["features"] for r in a["runs"] if r["feature_set"] != "wettability")


def test_preprocessing_fitted_on_training_fold_only():
    data = rows(6, per_group=2)
    data[-1]["material"] = data[-2]["material"] = "only-in-G5"
    df = C._frame(data, BASE)
    groups = df["specimen_code"].to_numpy()
    for tr, te in GroupKFold(n_splits=3, shuffle=True, random_state=0).split(df, groups=groups):
        pipe = C._pipeline("linear", BASE, 0).fit(df.iloc[tr][BASE], df["target"].iloc[tr])
        cats = pipe.named_steps["pre"].named_transformers_["cat"].named_steps["onehot"].categories_[0]
        if "G5" in set(groups[te]):
            assert "only-in-G5" not in cats  # the encoder never saw the held-out specimen
        scaler = pipe.named_steps["pre"].named_transformers_["num"].named_steps["scale"]
        assert scaler.mean_[0] == pytest.approx(df.iloc[tr]["temperature_c"].mean())


def test_model_persistence_and_tamper_detection(tmp_path):
    out = C.train_comparison(rows(6), "i_corr", BASE, "none", 1, POLICY, tmp_path, "p")
    run = next(r for r in out["runs"] if r["model_family"] == "linear" and r["feature_set"] == "wettability")
    model = C.load_model(tmp_path, run["model_path"], run["model_sha256"])
    pred = C.predict(model, run["features"], run["feature_domain"], "none", {"material": "steel", "surface_preparation": "a", "temperature_c": 25, "contact_angle_deg": 90})
    again = C.predict(C.load_model(tmp_path, run["model_path"], run["model_sha256"]), run["features"], run["feature_domain"], "none",
                      {"material": "steel", "surface_preparation": "a", "temperature_c": 25, "contact_angle_deg": 90})
    assert pred["prediction"] == pytest.approx(again["prediction"]) and not pred["warnings"]
    missing = C.predict(model, run["features"], run["feature_domain"], "none", {"material": "titanium", "contact_angle_deg": 175})
    assert any("not seen" in w for w in missing["warnings"]) and any("imputed" in w for w in missing["warnings"])
    assert any("outside the training range" in w for w in missing["warnings"])
    (tmp_path / run["model_path"]).write_bytes(b"tampered")
    with pytest.raises(C.MLError, match="hash"):
        C.load_model(tmp_path, run["model_path"], run["model_sha256"])
    with pytest.raises(C.MLError, match="escapes"):
        C.load_model(tmp_path, "../outside.joblib", run["model_sha256"])


def test_training_refused_when_not_ready(tmp_path):
    with pytest.raises(C.MLError, match="not ready"):
        C.train_comparison(rows(2), "i_corr", BASE, "none", 0, POLICY, tmp_path, "x")
