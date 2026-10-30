"""Print-ready HTML reports (open in a browser, Print -> Save as PDF). Built only from database records."""
from __future__ import annotations

import base64
import html
import io
from datetime import datetime, timezone

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app.core.config import APP_NAME, APP_VERSION  # noqa: E402

CA_NOTE = "Contact-angle classification describes the measured water wettability. It does not independently establish corrosion resistance or corrosion rate."
CSS = """
body{font:13px/1.45 'Segoe UI',system-ui,sans-serif;color:#111827;max-width:960px;margin:24px auto;padding:0 16px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 8px;border-bottom:2px solid #0e7490;padding-bottom:4px}
h3{font-size:14px;margin:18px 0 6px}table{border-collapse:collapse;width:100%;margin:6px 0 12px}
th,td{border:1px solid #d1d5db;padding:4px 6px;text-align:left;vertical-align:top}th{background:#f3f4f6;font-weight:600}
.num{text-align:right;font-variant-numeric:tabular-nums}.meta{color:#4b5563}.warn{color:#92400e}.bad{color:#b91c1c}
.tag{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.04em;padding:1px 6px;border-radius:3px;border:1px solid}
.measured{color:#065f46;border-color:#065f46}.calculated{color:#1e40af;border-color:#1e40af}.predicted{color:#6b21a8;border-color:#6b21a8}
.demo{background:#fef3c7;border:2px solid #b45309;color:#78350f;padding:10px 12px;font-weight:700;margin:12px 0}
.note{background:#f0f9ff;border-left:3px solid #0e7490;padding:6px 10px;margin:8px 0}img{max-width:100%;border:1px solid #d1d5db}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}code{font-size:12px}svg{max-width:100%;height:auto}
@media print{body{margin:0}h2{break-after:avoid}table,img,svg{break-inside:avoid}}
"""


def esc(v) -> str:
    return "" if v is None else html.escape(str(v))


def fmt(v, digits: int = 4) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        if v != 0 and (abs(v) >= 1e5 or abs(v) < 1e-3):
            return f"{v:.{digits - 1}e}"
        return f"{v:.{digits}g}"
    return esc(v)


def table(headers: list[str], rows: list[list], num_cols: set[int] | None = None) -> str:
    num_cols = num_cols or set()
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td class='num'>{c}</td>" if i in num_cols else f"<td>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def kv(pairs: list[tuple[str, object]]) -> str:
    return table(["Field", "Value"], [[esc(k), fmt(v) if isinstance(v, float) else esc(v if v not in (None, "") else "not recorded")] for k, v in pairs])


def svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    s = buf.getvalue()
    return s[s.find("<svg"):]


def _ax(title: str, xlabel: str, ylabel: str):
    fig, ax = plt.subplots(figsize=(6.2, 3.6), dpi=100)
    ax.set_title(title, fontsize=10)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    return fig, ax


def corrosion_plot(method: str, df: pd.DataFrame, result: dict | None, demo: bool) -> str:
    tag = " [DEMO - SYNTHETIC]" if demo else ""
    fit = (result or {}).get("fit", {})
    if method == "ocp":
        fig, ax = _ax("Open-circuit potential" + tag, "Time (s)", "E (V vs ref.)")
        ax.plot(df["time_s"], df["potential_V"], lw=1, color="#0e7490")
        if iv := fit.get("interval"):
            ax.axvspan(iv["t_start_s"], iv["t_end_s"], color="#0e7490", alpha=0.12, label="analysis interval")
            ax.legend(fontsize=8)
    elif method == "lpr":
        fig, ax = _ax("Linear polarisation" + tag, "i (uA/cm2)", "E (V vs ref.)")
        ax.plot(df["current_density_A_cm2"] * 1e6, df["potential_V"], ".", ms=2, color="#64748b", label="data")
        if line := fit.get("line"):
            ax.plot(np.array(line["i"]) * 1e6, line["e"], color="#dc2626", lw=1.5, label="fit (R_p)")
        ax.legend(fontsize=8)
    elif method == "pdp":
        fig, ax = _ax("Potentiodynamic polarisation" + tag, "log10 |i| (A/cm2)", "E (V vs ref.)")
        i = df["current_density_A_cm2"].to_numpy()
        ok = i != 0
        logs = np.log10(np.abs(i[ok]))
        ax.plot(logs, df["potential_V"].to_numpy()[ok], lw=1, color="#0e7490", label="data (|i|)")
        ax.set_xlim(np.percentile(logs, 1) - 0.5, logs.max() + 0.3)  # one near-zero sample must not stretch the axis
        for b, col in (("anodic", "#dc2626"), ("cathodic", "#2563eb")):
            if ln := (fit.get("lines") or {}).get(b):
                x = np.linspace(ln["log_i_range"][0] - 1.2, ln["log_i_range"][1], 20)
                ax.plot(x, ln["intercept_V"] + ln["slope_V_dec"] * x, "--", color=col, lw=1.2, label=f"{b} Tafel line")
        if pt := fit.get("intersection"):
            ax.plot(pt["log10_i"], pt["e_V"], "ko", ms=4, label="intersection")
        ax.legend(fontsize=8)
    else:
        fig, ax = _ax("Nyquist plot" + tag, "Z' (ohm)", "-Z'' (ohm)")
        ax.plot(df["z_real_ohm"], -df["z_imag_ohm"], "o-", ms=3, lw=0.8, color="#0e7490")
        ax.set_aspect("equal", adjustable="datalim")
    return svg(fig)


def _metric_rows(metrics: list[dict]) -> list[list]:
    rows = []
    for m in metrics:
        status = "valid" if m["valid"] else "<span class='bad'>unreliable</span>"
        warn = "<br>".join(f"<span class='warn'>{esc(w)}</span>" for w in m.get("warnings", []))
        rows.append([esc(m["label"]), fmt(m["value"]), esc(m["unit"]), "<span class='tag calculated'>CALCULATED</span>", f"<code>{esc(m['formula'])}</code>",
                     status, warn])
    return rows


def page(title: str, body: str, demo: bool) -> str:
    banner = "<div class='demo'>DEMO - SYNTHETIC DATA. This report was generated from synthetic demonstration records. It is not evidence of any material's behaviour.</div>" if demo else ""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body>{banner}<h1>{esc(title)}</h1>"
            f"<p class='meta'>Generated {stamp} by {APP_NAME} {APP_VERSION}. Values are taken from the local database; origins are labelled "
            f"<span class='tag measured'>MEASURED</span> <span class='tag calculated'>CALCULATED</span> <span class='tag predicted'>PREDICTED</span>.</p>"
            f"{body}{banner}</body></html>")


def experiment_report(ctx: dict) -> str:
    spec, exp, demo = ctx["specimen"], ctx["experiment"], ctx["is_demo"]
    parts = ["<h2>1. Specimen</h2>", kv([("Specimen ID", spec.code), ("Material", spec.material), ("Batch / source", spec.batch_source),
                                         ("Dimensions", spec.dimensions), ("Surface preparation", spec.surface_preparation),
                                         ("Roughness Ra (um)", spec.roughness_ra_um), ("Exposed area (cm2)", spec.exposed_area_cm2), ("Notes", spec.notes)])]
    parts += ["<h2>2. Experiment</h2>", kv([("Experiment ID", exp.code), ("Type", exp.experiment_type), ("Performed", exp.performed_at), ("Operator", exp.operator),
                                           ("Electrolyte", exp.electrolyte), ("Concentration", f"{exp.concentration_value} {exp.concentration_unit or ''}" if exp.concentration_value is not None else None),
                                           ("Temperature (C)", exp.temperature_c), ("Instrument", exp.instrument), ("Reference electrode", exp.reference_electrode),
                                           ("Procedure", exp.procedure), ("Status", exp.status), ("Notes", exp.notes)])]
    parts.append("<h2>3. Contact-angle measurements</h2>")
    cas = ctx["contact_angles"]
    if not cas:
        parts.append("<p class='meta'>No contact-angle measurements linked to this experiment.</p>")
    else:
        parts.append(f"<div class='note'>{esc(CA_NOTE)}</div>")
        parts.append(table(["Run", "Measured (UTC)", "Method", "Left (deg)", "Right (deg)", "Mean (deg)", "Class", "Status", "Image SHA-256", "Warnings"],
                           [[f"CA-{c['run'].id}", esc(c["run"].measured_at), esc(c["run"].method), fmt(c["run"].left_deg), fmt(c["run"].right_deg),
                             f"{fmt(c['run'].mean_deg)} <span class='tag measured'>MEASURED</span>", esc(c["run"].classification), esc(c["run"].status),
                             f"<code>{esc(c['sha256'][:16])}...</code>", "<br>".join(esc(w) for w in c["run"].warnings)] for c in cas], {3, 4, 5}))
        parts.append("<p class='meta'>Angles are measured from the image by the geometric pipeline (or operator-placed points for manual methods); "
                     "quality indicators are heuristic diagnostics, not calibrated uncertainties.</p>")
        imgs = [c for c in cas if c.get("overlay_b64")][:6]
        if imgs:
            parts.append("<div class='grid'>" + "".join(f"<figure><img alt='Annotated contact-angle image CA-{c['run'].id}' src='data:image/png;base64,{c['overlay_b64']}'>"
                                                        f"<figcaption class='meta'>CA-{c['run'].id}: annotated overlay (original image preserved separately).</figcaption></figure>"
                                                        for c in imgs) + "</div>")
    parts.append("<h2>4. Electrochemical runs</h2>")
    if not ctx["corrosion"]:
        parts.append("<p class='meta'>No electrochemical runs linked to this experiment.</p>")
    for c in ctx["corrosion"]:
        run = c["run"]
        parts.append(f"<h3>EC-{run.id}: {esc(c['method_label'])}</h3>")
        parts.append(kv([("Source file", c["raw_filename"]), ("Source SHA-256", c["raw_sha256"]), ("Points imported", run.n_points),
                         ("Column mapping", ", ".join(f"{k} = '{v}' [{run.units.get(k)}]" for k, v in run.column_mapping.items())),
                         ("Exposed area (cm2)", run.exposed_area_cm2), ("Area source", run.area_source), ("Reference electrode", run.reference_electrode),
                         ("Instrument", run.instrument), ("Analysis status", run.analysis_status)]))
        if c.get("plot"):
            parts.append(c["plot"])
        if c["metrics"]:
            parts.append(table(["Quantity", "Value", "Unit", "Origin", "Formula / method", "Status", "Warnings"], _metric_rows(c["metrics"]), {1}))
            assumptions = sorted({a for m in c["metrics"] for a in m.get("assumptions", [])})
            if assumptions:
                parts.append("<p><strong>Assumptions:</strong></p><ul>" + "".join(f"<li>{esc(a)}</li>" for a in assumptions) + "</ul>")
            params = {k: v for m in c["metrics"] for k, v in m.get("parameters", {}).items() if k in ("B_V", "B_source", "material_source", "equivalent_weight_g_eq", "density_g_cm3", "anodic_mV", "cathodic_mV", "selection", "e_low_V", "e_high_V")}
            if params:
                parts.append(kv([(k, v if not isinstance(v, list) else f"{v[0]} to {v[1]}") for k, v in params.items()]))
        else:
            parts.append("<p class='meta'>Not analysed yet; no derived quantities.</p>")
        for n in c.get("notes", []):
            parts.append(f"<div class='note'>{esc(n)}</div>")
    parts.append("<h2>5. Methods and limitations</h2><ul>"
                 "<li>Contact angle: OpenCV segmentation, specimen baseline (automatic substrate fit or operator-placed), sub-pixel boundary, local rotated-frame "
                 "polynomial tangent per side and spherical-cap fit. Classification: below 90 deg hydrophilic, above 90 deg hydrophobic, exactly 90 deg boundary.</li>"
                 "<li>Current density i = I / A with the recorded exposed area. R_p = dE/di near E_corr. i_corr = B / R_p only with a documented B. "
                 "Tafel: E = a + beta log10|i| on user-confirmed regions, intersection gives i_corr and E_corr. CR = 0.00327 i_corr EW / rho (mm/y; uA/cm2, g/eq, g/cm3).</li>"
                 "<li>OCP and EIS results are not converted into corrosion rates.</li>"
                 "<li>No compliance with any test standard is claimed. Synthetic-image accuracy of the contact-angle software is not a real-world metrology accuracy.</li></ul>")
    return page(f"Experiment report - {exp.code}", "".join(parts), demo)


def actual_vs_predicted(runs: list) -> str:
    fig, ax = _ax("Out-of-fold actual vs predicted", "Actual", "Predicted")
    lo, hi = np.inf, -np.inf
    for r in runs:
        if r.model_family == "mean":
            continue
        a = [p["actual"] for p in r.oof_predictions]
        p = [p["predicted"] for p in r.oof_predictions]
        ax.plot(a, p, "o", ms=4, alpha=0.75, label=r.name)
        lo, hi = min(lo, *a, *p), max(hi, *a, *p)
    if np.isfinite(lo):
        ax.plot([lo, hi], [lo, hi], "k--", lw=0.8, label="ideal")
    ax.legend(fontsize=7)
    return svg(fig)


def ml_report(runs: list, comparison: list[dict], interpretation: str) -> str:
    r0 = runs[0]
    demo = r0.includes_demo
    unit = r0.metrics.get("unit")
    parts = ["<h2>1. Question and design</h2>",
             "<p>Does adding the measured water contact angle to the recorded material and test conditions reduce the out-of-group prediction error "
             "of the electrochemical response? All configurations use the same target, the same specimen-grouped folds and pipelines whose "
             "imputation, scaling and encoding are fitted inside each training fold.</p>",
             kv([("Comparison ID", r0.comparison_id), ("Target", f"{r0.target} [{r0.target_unit}]"), ("Target transform", r0.target_transform),
                 ("Records", r0.n_records), ("Independent specimen groups", r0.n_groups), ("Split strategy", r0.split_strategy), ("Folds", r0.n_splits),
                 ("Seed", r0.seed), ("Dataset SHA-256", r0.dataset_hash), ("Readiness level", r0.readiness_level), ("Trained (UTC)", r0.created_at),
                 ("Software", ", ".join(f"{k} {v}" for k, v in r0.software_versions.items()))])]
    parts.append("<h2>2. Results (out-of-fold)</h2>")
    parts.append(table(["Model configuration", f"MAE [{unit}]", f"RMSE [{unit}]", "R2", "Fold MAE SD", "Groups", "Features", "Status"],
                       [[esc(r.name), fmt(r.metrics["mae"]), fmt(r.metrics["rmse"]), fmt(r.metrics["r2"]) if r.metrics.get("r2") is not None else f"N/A<br><span class='meta'>{esc(r.metrics.get('r2_note'))}</span>",
                         fmt(r.metrics.get("fold_mae_std")), r.n_groups, esc(", ".join(r.features) or "none"), "Recorded"] for r in runs], {1, 2, 3, 4, 5}))
    parts.append(table(["Model family", "Baseline MAE", "+ contact angle MAE", "Difference", "Folds improved"],
                       [[esc(c["model_family"]), fmt(c["baseline_mae"]), fmt(c["wettability_mae"]), fmt(c["delta_mae"]), f"{c['folds_improved']}/{c['n_folds']}"] for c in comparison], {1, 2, 3}))
    parts.append(f"<div class='note'><strong>Reading:</strong> {esc(interpretation)}</div>")
    parts.append(actual_vs_predicted(runs))
    parts.append("<p class='meta'>Predicted values are <span class='tag predicted'>PREDICTED</span> outputs of fitted models evaluated on held-out specimens; they are not measurements.</p>")
    if r0.warnings:
        parts.append("<h2>3. Advisories</h2><ul>" + "".join(f"<li>{esc(w)}</li>" for w in r0.warnings) + "</ul>")
    return page(f"ML comparison report - {r0.target}", "".join(parts), demo)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()
