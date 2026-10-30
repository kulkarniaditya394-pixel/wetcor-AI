"""Electrochemistry tests against hand calculations and SYNTHETIC curves with known parameters."""
import numpy as np
import pytest

from app.core.defaults import defaults
from app.services.electrochemistry import analysis as A
from app.services.electrochemistry import parser as P
from app.services.electrochemistry import synthetic as S
from app.services.electrochemistry import units as U

LIM = defaults()["electrochemistry"]
FE = {"equivalent_weight_g_eq": 27.9225, "density_g_cm3": 7.874, "source": "test fixture"}
BA, BC, ICORR = 0.06, 0.12, 5e-6
B_TRUE = BA * BC / (np.log(10) * (BA + BC))


def load(data: bytes, method: str, area=None, **kw):
    t = P.parse_table(data)
    s = P.suggest_mapping(t.columns, t.units_row, t.data)
    df, w = A.build_dataset(t, method, s["mapping"], s["units"], imag_convention=s["imag_convention"], area_cm2=area, **kw)
    return df, w, t, s


# ---------- units ----------

def test_current_and_area_conversions():
    assert U.convert(1500, "current", "uA", "mA") == pytest.approx(1.5)
    assert U.convert(1, "current", "nA", "A") == pytest.approx(1e-9)
    assert U.convert(250, "area", "mm2", "cm2") == pytest.approx(2.5)
    assert U.convert(1, "current_density", "A/m2", "uA/cm2") == pytest.approx(100)
    assert U.current_density([2e-6], 0.5)[0] == pytest.approx(4e-6)  # 2 uA over 0.5 cm2 = 4 uA/cm2


def test_unit_errors():
    with pytest.raises(U.UnitError):
        U.to_canonical([1.0], "current", None)  # no unit -> refuse, never assume
    with pytest.raises(U.UnitError):
        U.to_canonical([1.0], "current", "mV")
    with pytest.raises(U.UnitError):
        U.current_density([1e-6], None)
    with pytest.raises(U.UnitError):
        U.current_density([1e-6], 0)


def test_corrosion_rate_hand_calculation():
    # 0.00327 * 10 uA/cm2 * 27.92 g/eq / 7.87 g/cm3 = 0.11601 mm/y
    assert A.corrosion_rate_mm_per_year(10, 27.92, 7.87) == pytest.approx(0.00327 * 10 * 27.92 / 7.87)
    assert A.corrosion_rate_mm_per_year(10, 27.92, 7.87) == pytest.approx(0.11601, abs=1e-5)


@pytest.mark.parametrize("ew,rho,msg", [(None, 7.87, "Equivalent weight"), (27.92, None, "density")])
def test_corrosion_rate_requires_material_properties(ew, rho, msg):
    with pytest.raises(A.AnalysisError, match=msg):
        A.corrosion_rate_mm_per_year(10, ew, rho)


def test_stern_geary_from_tafel():
    assert A.stern_geary_from_tafel(0.06, 0.12) == pytest.approx(0.017371, abs=1e-6)


# ---------- parser ----------

def test_parse_comma_tab_semicolon_and_units_row():
    t = P.parse_table(b"Time (s),Potential (V)\n0,0.1\n1,0.2\n2,0.3\n3,0.4\n")
    assert t.delimiter == "comma" and t.columns == ["Time (s)", "Potential (V)"]
    t = P.parse_table(S.pdp_tsv())
    assert t.delimiter == "tab" and "Vf" in t.columns and t.units_row is not None
    assert t.metadata["TAG"] == "POTENTIODYNAMIC"
    t = P.parse_table(S.eis_semicolon())
    assert t.delimiter == "semicolon" and t.decimal_comma and t.data[0, 0] == pytest.approx(1e5)


def test_parse_unusual_headers_and_whitespace():
    data = b"Instrument = demo\n  Ewe/V   <I>/mA   time/s\n  0.10  0.5  0\n  0.11  0.6  1\n  0.12  0.7  2\n  0.13  0.8  3\n"
    t = P.parse_table(data)
    s = P.suggest_mapping(t.columns, t.units_row)
    assert s["mapping"] == {"potential": "Ewe/V", "current": "<I>/mA", "time": "time/s"}
    assert s["units"] == {"potential": "V", "current": "mA", "time": "s"}


def test_headerless_file_numbers_columns_and_needs_units():
    t = P.parse_table(b"0,1\n1,2\n2,3\n3,4\n4,5\n")
    assert t.columns == ["Column 1", "Column 2"] and any("No header" in w for w in t.warnings)
    with pytest.raises(U.UnitError):
        A.build_dataset(t, "ocp", {"time": "Column 1", "potential": "Column 2"}, {"time": "s", "potential": None})


@pytest.mark.parametrize("data", [b"", b"\x00\x01\x02\x03" * 100, b"just some words\nno numbers here\n"])
def test_malformed_files_rejected(data):
    with pytest.raises(P.ParseError):
        P.parse_table(data)


def test_missing_values_and_duplicates_reported():
    t = P.parse_table(b"t (s),E (V)\n0,0.1\n1,\n2,0.3\n2,0.3\n4,0.5\n5,0.6\n6,0.7\n")
    assert any("missing" in w for w in t.warnings) and any("duplicated" in w for w in t.warnings)
    df, w = A.build_dataset(t, "ocp", {"time": "t (s)", "potential": "E (V)"}, {"time": "s", "potential": "V"})
    assert len(df) == 6 and any("excluded" in x for x in w)


def test_mapping_validation():
    t = P.parse_table(S.ocp_csv())
    with pytest.raises(A.AnalysisError, match="requires"):
        A.build_dataset(t, "lpr", {"potential": "Time (s)"}, {"potential": "V"})
    with pytest.raises(A.AnalysisError, match="not used"):
        A.build_dataset(t, "ocp", {"time": "Time (s)", "potential": "Potential (V vs SCE)", "frequency": "Time (s)"}, {"time": "s", "potential": "V", "frequency": "Hz"})


# ---------- OCP ----------

def test_ocp_statistics_and_no_corrosion_rate():
    df, *_ = load(S.ocp_csv(), "ocp")
    r = A.analyze("ocp", df, {"t_start_s": 1500, "t_end_s": 1800}, LIM, reference_electrode="SCE", material=FE)
    names = {m["name"] for m in r["metrics"]}
    assert "i_corr" not in names and "corrosion_rate" not in names
    assert any("cannot be calculated from OCP" in n for n in r["notes"])
    assert any("cannot be derived from OCP" in w for w in r["warnings"])
    mean = next(m for m in r["metrics"] if m["name"] == "ocp_mean")
    assert mean["value"] == pytest.approx(-0.65, abs=0.002)


# ---------- LPR ----------

def test_lpr_rp_against_analytic_value():
    df, w, *_ = load(S.lpr_csv(), "lpr", area=1.0)
    assert any("I / A" in x for x in w)
    r = A.analyze("lpr", df, {"half_window_mV": 5}, LIM)
    rp = next(m for m in r["metrics"] if m["name"] == "rp")
    assert rp["valid"] and rp["value"] == pytest.approx(B_TRUE / ICORR, rel=0.02)
    assert "i_corr" not in {m["name"] for m in r["metrics"]}  # no B supplied -> no i_corr
    r = A.analyze("lpr", df, {"half_window_mV": 5, "stern_geary_B_V": B_TRUE, "B_source": "synthetic truth"}, LIM, material=FE)
    icorr = next(m for m in r["metrics"] if m["name"] == "i_corr")
    assert icorr["value"] == pytest.approx(5.0, rel=0.02) and icorr["parameters"]["B_source"] == "synthetic truth"
    cr = next(m for m in r["metrics"] if m["name"] == "corrosion_rate")
    assert cr["value"] == pytest.approx(0.00327 * icorr["value"] * FE["equivalent_weight_g_eq"] / FE["density_g_cm3"])


def test_lpr_refuses_b_without_source():
    df, *_ = load(S.lpr_csv(), "lpr", area=1.0)
    r = A.analyze("lpr", df, {"stern_geary_B_V": 0.026}, LIM)
    assert "i_corr" not in {m["name"] for m in r["metrics"]}
    assert any("source of the Stern-Geary" in n for n in r["notes"])


def test_lpr_wide_window_and_poor_fit_warn():
    data = S.lpr_csv(half=0.08, step=0.001)
    df, *_ = load(data, "lpr", area=1.0)
    r = A.analyze("lpr", df, {"half_window_mV": 70}, LIM)
    assert any("linear approximation" in w for w in r["warnings"])
    rp = next(m for m in r["metrics"] if m["name"] == "rp")
    assert not rp["valid"] and r["status"] == "invalid"


def test_lpr_requires_area_for_total_current():
    t = P.parse_table(S.lpr_csv())
    with pytest.raises(U.UnitError, match="area"):
        A.build_dataset(t, "lpr", {"potential": "E (mV)", "current": "I (uA)"}, {"potential": "mV", "current": "uA"}, area_cm2=None)


# ---------- Tafel ----------

def test_tafel_recovers_known_parameters():
    df, *_ = load(S.pdp_tsv(), "pdp", area=1.0)
    r = A.analyze("pdp", df, {"anodic_mV": [80, 250], "cathodic_mV": [80, 250]}, LIM, material=FE)
    m = {x["name"]: x for x in r["metrics"]}
    assert r["status"] == "ok" and r["fit"]["selection"] == "user_selected"
    assert m["beta_a"]["value"] == pytest.approx(60, rel=0.03)
    assert m["beta_c"]["value"] == pytest.approx(120, rel=0.03)
    assert m["i_corr"]["value"] == pytest.approx(5.0, rel=0.05)
    assert m["e_corr_tafel"]["value"] == pytest.approx(-0.65, abs=0.003)
    assert m["corrosion_rate"]["valid"] and m["corrosion_rate"]["origin"] == "calculated"


def test_tafel_auto_proposal_is_flagged_for_review():
    df, *_ = load(S.pdp_tsv(), "pdp", area=1.0)
    r = A.analyze("pdp", df, {}, LIM)
    assert r["fit"]["selection"] == "auto_proposed" and r["status"] == "limited"
    assert any("proposed automatically" in w for w in r["warnings"])


def test_tafel_rejects_curve_without_linear_regions():
    # Narrow sweep (+/-20 mV): no region spans a decade beyond 50 mV overpotential.
    df, *_ = load(S.pdp_tsv(span=0.02, step=0.0005), "pdp", area=1.0)
    r = A.analyze("pdp", df, {}, LIM)
    assert r["status"] == "invalid" and "i_corr" not in {m["name"] for m in r["metrics"]}
    r = A.analyze("pdp", df, {"anodic_mV": [5, 20], "cathodic_mV": [5, 20]}, LIM)
    assert r["status"] == "invalid"
    icorr = [m for m in r["metrics"] if m["name"] == "i_corr"]
    assert not icorr or not icorr[0]["valid"]


def test_semilog_zero_and_negative_currents():
    out = A.log_current(np.array([-1e-6, 0.0, 1e-4]))
    assert out["excluded_zero"] == 1 and np.isnan(out["log10_abs"][1])
    assert out["log10_abs"][0] == pytest.approx(-6) and out["log10_abs"][2] == pytest.approx(-4)
    assert out["sign"].tolist() == [-1, 0, 1]


def test_zero_crossing_interpolation():
    e, how = A.zero_crossing_potential(np.array([-0.2, -0.1, 0.0]), np.array([-2.0, -1.0, 1.0]))
    assert e == pytest.approx(-0.05) and "interpolated" in how


# ---------- EIS ----------

def test_eis_columns_sign_convention_and_metrics():
    df, w, t, s = load(S.eis_semicolon(noise=0), "eis", area=2.0)
    assert s["imag_convention"] == "negated"
    assert (df["z_imag_ohm"] < 0).all()  # capacitive: Z'' negative after correcting '-Im(Z)' column
    r = A.analyze("eis", df, {}, LIM, area_cm2=2.0)
    m = {x["name"]: x for x in r["metrics"]}
    z_lo = abs(S.randles_cpe(np.array([1e-2]))[0])
    assert m["z_mod_low_f"]["value"] == pytest.approx(z_lo, rel=1e-4)
    assert m["z_mod_low_f_area"]["value"] == pytest.approx(2 * z_lo, rel=1e-4)
    assert m["eis_decades"]["value"] == pytest.approx(7)
    assert not any("corrosion" in x["name"] for x in r["metrics"])
    assert r["warnings"] == []


def test_eis_rejects_non_positive_frequency():
    t = P.parse_table(b"f (Hz),Zre (ohm),Zim (ohm)\n0,1,1\n1,1,1\n2,1,1\n3,1,1\n4,1,1\n")
    with pytest.raises(A.AnalysisError, match="positive"):
        A.build_dataset(t, "eis", {"frequency": "f (Hz)", "z_real": "Zre (ohm)", "z_imag": "Zim (ohm)"}, {"frequency": "Hz", "z_real": "ohm", "z_imag": "ohm"})
