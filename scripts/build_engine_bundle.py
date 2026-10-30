"""Pack the analysis code that runs in the browser (Pyodide) into frontend/public/engine/app.zip.

Only pure-analysis modules are included (no FastAPI, database or file storage). Re-run after changing any of them,
then commit the zip. Usage:  backend\.venv\Scripts\python scripts\build_engine_bundle.py
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "backend" / "app"
OUT = ROOT / "frontend" / "public" / "engine"
FILES = [
    "__init__.py", "browser_engine.py",
    "core/__init__.py", "core/defaults.py", "core/serial.py",
    "services/__init__.py", "services/quick.py",
    "services/wettability/__init__.py", "services/wettability/geometry.py", "services/wettability/detection.py", "services/wettability/overlay.py",
    "services/electrochemistry/__init__.py", "services/electrochemistry/units.py", "services/electrochemistry/parser.py",
    "services/electrochemistry/analysis.py", "services/electrochemistry/materials.py",
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    zpath = OUT / "app.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            info = zipfile.ZipInfo(f"app/{f}", date_time=(2026, 1, 1, 0, 0, 0))  # fixed timestamp: reproducible bytes
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (APP / f).read_bytes())
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    (OUT / "app.zip.sha256").write_text(digest + "\n")
    print(f"wrote frontend/public/engine/app.zip ({zpath.stat().st_size / 1024:.0f} kB, {len(FILES)} modules) sha256 {digest[:16]}")


if __name__ == "__main__":
    main()
