"""Arduino corrosion rig: parsing of real Serial Monitor output, checks, verdicts and hand-calculated rates."""
import pytest

from app.services import quick
from app.services.electrochemistry import arduino as RIG

SAMPLE = """Good ACS712 AO: 2.527 V
Corroded ACS712 AO: 2.528 V
Good current: 0.145 A
Corroded current: 0.153 A
Current difference: 0.009 A
Good LM393 AO: 5.000 V
Corroded LM393 AO: 4.959 V
Signed LM difference: -0.041 V
Absolute LM difference: 0.041 V
RESULT: HEALTHY ELECTRODE
"""
FE = {"profile": "Fe"}


def analyse(text=SAMPLE, settings=None, material=None):
    p = quick.rig_parse(text)
    return quick.rig_analyze({**p, "settings": settings or {}, "material": material})


def test_real_output_reads_every_line():
    p = RIG.parse_output(SAMPLE)
    assert p["n_cycles"] == 1 and p["device_verdict"] == "healthy" and p["device_result"] == "HEALTHY ELECTRODE"
    r = p["readings"]
    assert r["good_acs_v"] == 2.527 and r["corroded_acs_v"] == 2.528 and r["good_current_a"] == 0.145 and r["corroded_current_a"] == 0.153
    assert r["current_diff_a"] == 0.009 and r["good_lm_v"] == 5.0 and r["corroded_lm_v"] == 4.959
    assert r["lm_diff_signed_v"] == -0.041 and r["lm_diff_abs_v"] == 0.041
    assert p["missing"] == [] and p["unrecognised_lines"] == []


def test_sensor_identified_from_the_numbers():
    s = RIG.infer_sensor(RIG.parse_output(SAMPLE)["readings"])
    assert s["variant"].startswith("ACS712-05B") and s["sensitivity_v_per_a"] == 0.185 and s["zero_v"] == 2.5


def test_serial_monitor_timestamps_and_other_formats():
    stamped = "\n".join(f"12:03:{i:02d}.512 -> {line}" for i, line in enumerate(SAMPLE.splitlines()))
    assert RIG.parse_output(stamped)["readings"] == RIG.parse_output(SAMPLE)["readings"]
    messy = "Booting rig...\n\n  good current = 145 mA\ncorroded CURRENT:0.153A\n----\nResult - CORRODED ELECTRODE\n"
    p = RIG.parse_output(messy)
    assert p["readings"]["good_current_a"] == pytest.approx(0.145) and p["readings"]["corroded_current_a"] == 0.153
    assert p["device_verdict"] == "corroded" and "Booting rig..." in p["unrecognised_lines"]


@pytest.mark.parametrize("text,verdict", [("HEALTHY ELECTRODE", "healthy"), ("CORRODED ELECTRODE", "corroded"), ("NOT CORRODED", "healthy"),
                                          ("NOT HEALTHY", "corroded"), ("ELECTRODE CORRODING", "corroded"), ("CHECK WIRING", "unknown")])
def test_verdict_words(text, verdict):
    assert RIG.parse_output(f"Good current: 0.1 A\nCorroded current: 0.2 A\nRESULT: {text}\n")["device_verdict"] == verdict


def test_multiple_cycles_are_averaged_with_real_scatter():
    cycles = "".join(SAMPLE.replace("0.153", f"0.{v}") for v in (150, 153, 156, 153))
    p = RIG.parse_output(cycles + "Good current: 0.2 A\n")  # trailing partial cycle from the copy
    assert p["n_cycles"] == 4 and p["readings"]["corroded_current_a"] == pytest.approx(0.153) and p["spread"]["corroded_current_a"] > 0
    assert any("incomplete" in w for w in p["warnings"])
    r = quick.rig_analyze({**p, "settings": {}})
    assert any(c["key"] == "repeatability" for c in r["checks"])


def test_changing_verdict_between_cycles_is_reported():
    p = RIG.parse_output(SAMPLE + SAMPLE.replace("HEALTHY ELECTRODE", "CORRODED ELECTRODE") + SAMPLE)
    assert p["device_verdict"] == "healthy" and any("changed between cycles" in w for w in p["warnings"])


@pytest.mark.parametrize("text", ["", "   \n", "hello world\nno numbers", "Good current: 0.1 A\n"])
def test_bad_input_is_refused(text):
    with pytest.raises(quick.QuickError):
        quick.rig_parse(text)


def test_wrong_unit_is_refused():
    with pytest.raises(quick.QuickError, match="Unexpected unit"):
        quick.rig_parse("Good current: 0.1 V\nCorroded current: 0.2 A\n")


def test_difference_below_adc_step_is_not_called_real():
    r = analyse()
    assert r["comparison"] == "no_difference" and r["agrees_with_device"] is True
    assert r["resolution"]["adc_step_a"] == pytest.approx(5 / 1023 / 0.185)
    assert r["currents"]["delta_a"] == pytest.approx(0.009)
    assert {c["key"]: c["status"] for c in r["checks"]}["lm_range"] == "warn"  # 5.000 V is ADC full scale


def test_large_difference_is_reported_and_can_disagree_with_device():
    t = SAMPLE.replace("Corroded current: 0.153 A", "Corroded current: 0.450 A").replace("Current difference: 0.009 A", "Current difference: 0.305 A").replace("Corroded ACS712 AO: 2.528 V", "Corroded ACS712 AO: 2.583 V")
    r = analyse(t)
    assert r["comparison"] == "difference" and r["agrees_with_device"] is False and any("disagree" in w for w in r["warnings"])
    assert analyse(t.replace("HEALTHY ELECTRODE", "CORRODED ELECTRODE"))["agrees_with_device"] is True


def test_rate_needs_area_and_material_never_defaults():
    r = analyse()
    assert set(r["needs"]) == {"exposed electrode area", "material"} and not r["metrics"]
    assert analyse(settings={"exposed_area_cm2": 10})["needs"] == ["material"]
    assert analyse(material=FE)["needs"] == ["exposed electrode area"]
    r = analyse(settings={"exposed_area_cm2": 10}, material={"equivalent_weight_g_eq": 27.9, "density_g_cm3": 7.87})
    assert r["needs"] == ["source of the material properties"]


def test_faraday_rate_hand_calculation_and_labels():
    r = analyse(settings={"exposed_area_cm2": 12.5}, material=FE)
    m = {x["name"]: x for x in r["metrics"]}
    i_ua = 0.153 / 12.5 * 1e6
    ew, rho = round(55.845 / 2, 4), 7.874
    assert m["rig_current_density"]["value"] == pytest.approx(12240)
    assert m["rig_faraday_rate"]["value"] == pytest.approx(0.00327 * i_ua * ew / rho)
    assert m["rig_mass_loss_rate"]["value"] == pytest.approx(0.153 * ew / 96485 * 86400)
    assert "Faradaic" in m["rig_faraday_rate"]["assumptions"][0] and m["rig_faraday_rate"]["parameters"]["range_low_mm_y"] < m["rig_faraday_rate"]["value"]
    assert m["rig_excess_rate"]["valid"] is False  # difference below resolution
    assert any("upper bound" in w for w in r["warnings"])  # far too large for natural corrosion
    assert not {"i_corr", "rp", "corrosion_rate"} & set(m)  # never mixed with electrochemical ML targets


def test_weight_loss_rate_hand_calculation_and_severity():
    s = {"exposed_area_cm2": 10, "mass_before_g": 25.0, "mass_after_g": 24.9, "exposure_h": 100}
    r = analyse(settings=s, material=FE)
    m = {x["name"]: x for x in r["metrics"]}
    assert m["rig_gravimetric_rate"]["value"] == pytest.approx(8.76e4 * 0.1 / (10 * 100 * 7.874))
    assert r["severity"]["label"] == "severe" and r["severity"]["basis"] == "weight loss"
    assert m["rig_current_efficiency"]["value"] > 0
    assert any("corrosion products" in w for w in analyse(settings={**s, "mass_after_g": 25.1}, material=FE)["warnings"])


def test_zero_current_calibration_changes_currents():
    r = analyse(settings={"zero_good_ao_v": 2.527, "zero_corroded_ao_v": 2.5275})
    assert r["currents"]["calibrated"] and r["currents"]["good_a"] == pytest.approx(0) and r["currents"]["corroded_a"] == pytest.approx(0.0005 / 0.185)


def test_rig_endpoints(client):
    p = client.post("/api/corrosion/rig/parse", json={"text": SAMPLE}).json()
    assert p["device_verdict"] == "healthy"
    r = client.post("/api/corrosion/rig/analyze", json={**p, "settings": {"exposed_area_cm2": 12.5}, "material": FE}).json()
    assert r["comparison"] == "no_difference" and r["metrics"]
    assert client.post("/api/corrosion/rig/parse", json={"text": "nothing"}).status_code == 422
