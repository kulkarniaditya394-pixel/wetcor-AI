"""Entry point for the in-browser (Pyodide) analysis engine used by the hosted static site.

The web worker calls dispatch(); everything is JSON in / JSON out, files arrive as bytes. Nothing is stored
or transmitted: the analysis runs inside the visitor's browser.
"""
from __future__ import annotations

import json
import traceback

from app.core.serial import clean
from app.services import quick


def dispatch(fn: str, args_json: str = "{}", blob: bytes | None = None) -> str:
    args = json.loads(args_json or "{}")
    if blob is not None and hasattr(blob, "to_py"):  # JS Uint8Array -> bytes (Pyodide)
        blob = bytes(blob.to_py())
    try:
        if fn == "ping":
            out = {"engine": "wetcor-browser-engine", "ok": True}
        elif fn == "wettability_analyze":
            out = quick.wettability_analyze(blob or b"", args.get("params", {}), None, args.get("include_auto", True))
        elif fn == "corrosion_methods":
            out = quick.corrosion_methods()
        elif fn == "corrosion_preview":
            out = quick.corrosion_preview(blob or b"", args.get("filename", ""))
        elif fn == "rig_parse":
            out = quick.rig_parse(args.get("text", ""))
        elif fn == "rig_analyze":
            out = quick.rig_analyze(args)
        elif fn == "corrosion_quick":
            out = quick.corrosion_quick(blob or b"", args["meta"], args.get("params"), args.get("material"), args.get("reference_electrode"))
        else:
            return json.dumps({"ok": False, "status": 404, "detail": f"Unknown engine function '{fn}'."})
        return json.dumps({"ok": True, "result": clean(out)})
    except quick.QuickError as exc:
        return json.dumps({"ok": False, "status": exc.status, "detail": str(exc)})
    except Exception as exc:  # noqa: BLE001 - report to the page instead of dying inside the worker
        return json.dumps({"ok": False, "status": 500, "detail": f"Engine error: {exc}", "trace": traceback.format_exc()[-1500:]})
