"""Export the showcase test as static files for hosting without the backend (Netlify static demo mode).

Builds the showcase in a throw-away workspace through the real API (same code path as the app), then writes
frontend/public/showcase-static/: snapshot.json, source.png, overlay.png, report.html.
Re-run after changing anything in data/showcase/ or the analysis code, then commit the result.

Usage (from the wetcor-ai folder):  backend\\.venv\\Scripts\\python scripts\\export_static_showcase.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
warnings.filterwarnings("ignore")

OUT = ROOT / "frontend" / "public" / "showcase-static"


def main() -> None:
    from fastapi.testclient import TestClient

    from app.core.config import use_data_dir
    from app.database import session as S

    with tempfile.TemporaryDirectory() as tmp:
        use_data_dir(Path(tmp) / "data", Path(tmp) / "models")
        S.reset_engine()
        from app.main import app

        with TestClient(app) as c:
            def get(path: str):
                r = c.get(path)
                r.raise_for_status()
                return r

            sc = c.post("/api/demo/showcase/load")
            sc.raise_for_status()
            st = get("/api/demo/showcase").json()
            show = st["showcase"]
            spec = get(f"/api/specimens/{show['specimen_id']}").json()
            ca = get(f"/api/wettability/measurements/{show['contact_angle_run_ids'][0]}").json()
            runs = {r["method"]: r["id"] for r in show["corrosion_runs"]}
            snap = {
                "generated_from": "data/showcase/showcase.json via scripts/export_static_showcase.py",
                "manifest": st["manifest"], "showcase": show, "spec": spec, "ca": ca,
                "pdp": get(f"/api/corrosion/runs/{runs['pdp']}").json(), "pdpData": get(f"/api/corrosion/runs/{runs['pdp']}/data").json(),
                "ocp": get(f"/api/corrosion/runs/{runs['ocp']}").json(), "ocpData": get(f"/api/corrosion/runs/{runs['ocp']}/data").json(),
                "images": {"source": "/showcase-static/source.png", "overlay": "/showcase-static/overlay.png"}, "report": "/showcase-static/report.html",
            }
            source_id = next(a["id"] for a in spec["artifacts"] if a["kind"] == "source_image")
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "source.png").write_bytes(get(f"/api/artifacts/{source_id}/download").content)
            (OUT / "overlay.png").write_bytes(get(f"/api/artifacts/{ca['overlay_artifact_id']}/download").content)
            (OUT / "report.html").write_text(get(f"/api/reports/experiment/{show['experiment_id']}").text, encoding="utf-8")
            (OUT / "snapshot.json").write_text(json.dumps(snap, separators=(",", ":")), encoding="utf-8")
        S.reset_engine()
    for f in sorted(OUT.iterdir()):
        print(f"wrote frontend/public/showcase-static/{f.name} ({f.stat().st_size / 1024:.0f} kB)")
    print(f"contact angle {ca['mean_deg']} deg ({ca['method']})")


if __name__ == "__main__":
    main()
