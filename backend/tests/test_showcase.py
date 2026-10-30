"""Showcase example: built from the manifest by the normal analysis code, flagged as demo, removable."""


def test_showcase_load_open_and_reset(client):
    st = client.get("/api/demo/showcase").json()
    assert st["loaded"] is False and st["manifest"]["contact_angle"]["source"]["licence"] == "CC BY-SA 4.0"
    out = client.post("/api/demo/showcase/load").json()
    assert client.post("/api/demo/showcase/load").status_code == 409
    ca = client.get(f"/api/wettability/measurements/{out['contact_angle_run_ids'][0]}").json()
    assert ca["is_demo"] and ca["method"] == "manual_corrected" and ca["auto_result"] is not None
    assert 105 < ca["mean_deg"] < 120 and ca["classification"] == "hydrophobic"
    methods = {r["method"] for r in out["corrosion_runs"]}
    assert methods == {"ocp", "pdp"}
    pdp = next(r for r in out["corrosion_runs"] if r["method"] == "pdp")
    metrics = {m["name"]: m for m in client.get(f"/api/corrosion/runs/{pdp['id']}/metrics").json()}
    assert metrics["i_corr"]["valid"] and abs(metrics["i_corr"]["value"] - 8.0) / 8 < 0.08  # synthetic truth 8 uA/cm2
    assert metrics["corrosion_rate"]["parameters"]["material_source"]
    rep = client.get(f"/api/reports/experiment/{out['experiment_id']}")
    assert "DEMO - SYNTHETIC" in rep.text and "DEMO-SHOWCASE-E01" in rep.text
    assert client.get("/api/specimens").json()["total"] == 0  # never in the real workspace
    assert client.post("/api/demo/load").status_code == 200  # demo workspace still loadable alongside
    client.delete("/api/demo", params={"confirm": "RESET-DEMO"})
    assert client.get("/api/demo/showcase").json()["loaded"] is False
