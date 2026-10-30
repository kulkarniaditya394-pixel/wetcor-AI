"""Sessile-drop contact-angle pipeline (OpenCV segmentation + geometric fitting).

Steps: validate/decode -> optional ROI -> grey-level segmentation (Otsu or user threshold)
-> specimen baseline (auto from the substrate profile, or user-placed) -> droplet component above
the baseline -> boundary contour -> contact points -> local polynomial tangents per side and a
spherical-cap circle fit -> diagnostics, warnings, classification.

The function never modifies the input bytes or decoded arrays. When baseline, contact points or the
boundary cannot be identified reliably it returns status "failed" or "needs_correction" instead of
an angle.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from scipy.ndimage import map_coordinates

from app.services.wettability import geometry as g

ALGORITHM_VERSION = "ca-1.0.0"
UNCERTAINTY_NOTE = (
    "Quality indicators are heuristic diagnostics of the image and fit. They are not a calibrated "
    "measurement uncertainty; repeatability must be established by repeated drops."
)
CUT_PX = 1.5  # droplet pixels must lie at least this far above the baseline
MAX_PIXELS = 50_000_000


class ImageError(ValueError):
    pass


def decode_image(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    if not data:
        raise ImageError("Empty image.")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ImageError("Unsupported or corrupt image (PNG, JPEG, BMP or TIFF expected).")
    if img.dtype == np.uint16:
        img = (img / 257).astype(np.uint8)
    elif img.dtype != np.uint8:
        raise ImageError(f"Unsupported pixel type {img.dtype}.")
    h, w = img.shape[:2]
    if min(h, w) < 32:
        raise ImageError(f"Image too small ({w}x{h}); at least 32 px per side required.")
    if h * w > MAX_PIXELS:
        raise ImageError("Image exceeds 50 megapixels.")
    if img.ndim == 2:
        gray, bgr = img, cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    else:
        bgr, gray = img, cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return bgr, gray


def _diag(key: str, label: str, value: Any, status: str, unit: str = "", note: str = "") -> dict:
    return {"key": key, "label": label, "value": value, "unit": unit, "status": status, "note": note}


def _segment(sub: np.ndarray, threshold: float | None, polarity: str) -> tuple[np.ndarray, float, str, float, np.ndarray]:
    blur = cv2.GaussianBlur(sub, (5, 5), 0)
    otsu, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = float(threshold) if threshold is not None else float(otsu)
    if polarity == "auto":
        polarity = "dark_drop" if np.median(blur[:2, :]) > t else "light_drop"
    mask = (blur < t) if polarity == "dark_drop" else (blur > t)
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    fg, bg = blur[mask], blur[~mask]
    contrast = float(abs(bg.mean() - fg.mean())) if fg.size and bg.size else 0.0
    return mask, t, polarity, contrast, cv2.GaussianBlur(sub.astype(np.float32), (5, 5), 0)


def _refine_subpixel(img: np.ndarray, pts: np.ndarray, t: float) -> np.ndarray:
    """Move pixel contour points to the sub-pixel threshold crossing along the local intensity gradient."""
    gy, gx = np.gradient(img)
    xi, yi = pts[:, 0].astype(int), pts[:, 1].astype(int)
    g = np.column_stack([gx[yi, xi], gy[yi, xi]])
    norm = np.hypot(g[:, 0], g[:, 1])
    ok = norm > 1e-6
    g[ok] /= norm[ok, None]
    offs = np.linspace(-2.5, 2.5, 11)
    samples = pts[:, None, :] + offs[None, :, None] * g[:, None, :]
    vals = map_coordinates(img, [samples[..., 1].ravel(), samples[..., 0].ravel()], order=1, mode="nearest").reshape(len(pts), len(offs))
    d = vals - t
    a, b = d[:, :-1], d[:, 1:]
    cross = (np.sign(a) != np.sign(b)) & (a != b)
    with np.errstate(divide="ignore", invalid="ignore"):
        pos = offs[:-1] + (-a / (b - a)) * (offs[1] - offs[0])
    pos = np.where(cross, pos, np.inf)
    best = np.abs(pos).argmin(axis=1)
    shift = pos[np.arange(len(pts)), best]
    ok &= np.isfinite(shift)
    out = pts.copy()
    out[ok] += shift[ok, None] * g[ok]
    return out


def _detect_baseline(mask: np.ndarray) -> tuple[tuple[float, float, float] | None, str]:
    """Fit the specimen surface from the top foreground profile at both ROI edges (y = a*x + b)."""
    h, w = mask.shape
    has = mask.any(axis=0)
    top = np.where(has, mask.argmax(axis=0), -1).astype(float)
    band = max(3, int(0.12 * w))
    left, right = top[:band], top[w - band:]
    if (left >= 0).mean() < 0.6 or (right >= 0).mean() < 0.6:
        return None, "Specimen surface not visible on both sides of the image/ROI. Widen the ROI or mark the baseline manually."
    x = np.r_[np.arange(band), np.arange(w - band, w)].astype(float)
    y = np.r_[left, right]
    keep = y >= 0
    x, y = x[keep], y[keep]
    for _ in range(3):
        a, b = np.polyfit(x, y, 1)
        r = y - (a * x + b)
        mad = 1.4826 * np.median(np.abs(r - np.median(r)))
        keep = np.abs(r) <= max(1.5, 3 * mad)
        if keep.sum() < 6:
            return None, "Specimen surface profile is too irregular to fit a baseline. Mark the baseline manually."
        x, y = x[keep], y[keep]
    a, b = np.polyfit(x, y, 1)
    rms = float(np.sqrt(np.mean((y - (a * x + b)) ** 2)))
    if rms > 2.0:
        return None, f"Specimen surface is not straight (RMS {rms:.1f} px). Mark the baseline manually."
    cols = np.arange(w)
    rising = (top >= 0) & (top < a * cols + b - 3)
    if not rising[band:w - band].any():
        return None, "No droplet rises above the detected surface."
    return (float(a), float(b), rms), ""


def _waist(u: np.ndarray, v: np.ndarray) -> float | None:
    """Height of an interior width minimum (a 'neck'), which suggests a reflection below the true contact line."""
    vb = np.round(v).astype(int)
    if vb.max() < 10:
        return None
    lo = np.full(vb.max() + 1, np.inf)
    hi = np.full(vb.max() + 1, -np.inf)
    np.minimum.at(lo, vb, u)
    np.maximum.at(hi, vb, u)
    width = np.where(np.isfinite(lo), hi - lo, np.nan)
    width = np.convolve(np.nan_to_num(width), np.ones(3) / 3, mode="same")
    peak = np.nanmax(width)
    for i in range(4, len(width) - 4):
        if width[i] < 0.85 * width[:i].max() and width[i] < 0.85 * width[i:].max() and width[i] < 0.9 * peak and width[i] == width[i - 3:i + 4].min():
            return float(i)
    return None


def _failed(result: dict, message: str) -> dict:
    result["errors"].append(message)
    result["status"] = "failed"
    return result


def analyze(data: bytes, params: dict | None = None, limits: dict | None = None) -> dict:
    from app.core.defaults import defaults

    p = params or {}
    lim = {**defaults()["wettability"], **(limits or {})}
    result: dict[str, Any] = {
        "status": "ok", "method": None, "algorithm_version": ALGORITHM_VERSION,
        "left_deg": None, "right_deg": None, "mean_deg": None, "lr_diff_deg": None, "classification": None,
        "methods": {}, "geometry": {}, "diagnostics": [], "warnings": [], "errors": [],
        "image": None, "params": dict(p), "limits": lim, "uncertainty_note": UNCERTAINTY_NOTE,
        "manual_correction": False, "suggested_baseline": None,
    }
    diags, warns = result["diagnostics"], result["warnings"]
    try:
        bgr, gray = decode_image(data)
    except ImageError as exc:
        return _failed(result, str(exc))
    H, W = gray.shape
    result["image"] = {"width": W, "height": H}

    roi = p.get("roi")
    if roi:
        x0, y0 = max(0, int(roi[0])), max(0, int(roi[1]))
        x1, y1 = min(W, int(roi[0] + roi[2])), min(H, int(roi[1] + roi[3]))
        if x1 - x0 < 32 or y1 - y0 < 32:
            return _failed(result, "Region of interest is smaller than 32x32 px.")
    else:
        x0, y0, x1, y1 = 0, 0, W, H
    result["geometry"]["roi"] = [x0, y0, x1 - x0, y1 - y0]
    sub = gray[y0:y1, x0:x1]

    clip = float(np.mean((sub <= 0) | (sub >= 255)))
    diags.append(_diag("clipping", "Saturated pixels", round(clip * 100, 2), "warn" if clip > lim["clip_fraction_warn"] else "pass", "%",
                       "Over- or under-exposure shifts the detected edge." if clip > lim["clip_fraction_warn"] else ""))

    if p.get("mode") == "manual_tangent":
        return _manual_tangent(result, p, lim)

    corrected = any(p.get(k) is not None for k in ("baseline", "contact_left", "contact_right", "threshold", "fit_radius_px")) or p.get("polarity", "auto") != "auto"
    result["manual_correction"] = corrected

    mask, thr, polarity, contrast, blur_f = _segment(sub, p.get("threshold"), p.get("polarity", "auto"))
    result["params"].update({"threshold_used": round(thr, 1), "polarity_used": polarity})
    c_status = "fail" if contrast < lim["fail_contrast_levels"] else "warn" if contrast < lim["min_contrast_levels"] else "pass"
    diags.append(_diag("contrast", "Droplet/background contrast", round(contrast, 1), c_status, "grey levels"))
    if c_status == "fail":
        return _failed(result, "Contrast is too low for reliable automatic segmentation. Improve back-lighting, adjust the threshold, or use manual tangent mode.")
    if c_status == "warn":
        warns.append("Low contrast: the detected boundary may be biased. Verify the overlay.")

    # Baseline
    try:
        if p.get("baseline"):
            frame = g.make_frame(*p["baseline"])
            diags.append(_diag("baseline", "Baseline", "manual", "pass", note=f"Tilt {frame.tilt_deg:.2f} deg"))
        else:
            line, reason = _detect_baseline(mask)
            if line is None:
                diags.append(_diag("baseline", "Baseline", "not detected", "fail", note=reason))
                result["status"] = "failed"
                result["errors"].append(reason)
                return result
            a, b, rms = line
            frame = g.make_frame((x0, b + y0), (x1 - 1, a * (x1 - 1 - x0) + b + y0))
            diags.append(_diag("baseline", "Baseline", "auto (substrate profile)", "pass", note=f"Fit RMS {rms:.2f} px; tilt {frame.tilt_deg:.2f} deg"))
    except g.GeometryError as exc:
        return _failed(result, str(exc))
    corners = frame.to_uv(np.array([[x0, y0], [x1, y0], [x0, y1], [x1, y1]], dtype=float))
    result["geometry"]["baseline"] = frame.to_xy([[corners[:, 0].min(), 0], [corners[:, 0].max(), 0]]).round(2).tolist()
    result["geometry"]["baseline_points"] = [frame.origin.round(2).tolist(), (frame.origin + frame.d * 100).round(2).tolist()]
    result["geometry"]["tilt_deg"] = round(frame.tilt_deg, 3)

    # Droplet component above the baseline
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(float)
    umap = (xx - frame.origin[0]) * frame.d[0] + (yy - frame.origin[1]) * frame.d[1]
    vmap = (xx - frame.origin[0]) * frame.n[0] + (yy - frame.origin[1]) * frame.n[1]
    above = (mask & (vmap > CUT_PX)).astype(np.uint8)
    n_cc, labels, stats, _ = cv2.connectedComponentsWithStats(above, connectivity=8)
    min_area = max(50, int(0.0005 * above.size))
    best, best_area = 0, 0
    for k in np.argsort(-stats[1:, cv2.CC_STAT_AREA])[:6] + 1:
        area = stats[k, cv2.CC_STAT_AREA]
        if area < min_area:
            break
        if vmap[labels == k].min() <= CUT_PX + 3 and area > best_area:
            best, best_area = k, area
    if best == 0:
        diags.append(_diag("droplet", "Droplet region", "not found", "fail"))
        return _failed(result, "No droplet touching the baseline was detected. Check the ROI, threshold and baseline.")
    comp = labels == best
    touches = {"left": comp[:, 0].any(), "right": comp[:, -1].any(), "top": comp[0, :].any()}
    if touches["left"] or touches["right"]:
        low_l, low_r = vmap[comp & (xx == x0)], vmap[comp & (xx == x1 - 1)]
        spans = low_l.size and low_r.size and low_l.min() <= CUT_PX + 4 and low_r.min() <= CUT_PX + 4
        msg = ("Region above the baseline spans the full ROI width near the baseline: the baseline probably lies below the specimen surface. Move it up."
               if spans else "Droplet is clipped by the left/right image or ROI border; contact points cannot be located.")
        diags.append(_diag("clipping_drop", "Droplet inside frame", "no", "fail", note=msg))
        return _failed(result, msg)
    if touches["top"]:
        warns.append("Droplet region touches the top of the image/ROI (clipped apex or dispensing needle). Circle fit disabled; local tangent only.")

    contours, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    pts = _refine_subpixel(blur_f, max(contours, key=len)[:, 0, :].astype(float), thr) + [x0, y0]
    uv = frame.to_uv(pts)
    free = uv[:, 1] > lim["exclude_px"]
    n_free = int(free.sum())
    diags.append(_diag("contour_points", "Boundary points above baseline", n_free, "pass" if n_free >= lim["min_contour_points"] else "fail"))
    if n_free < lim["min_contour_points"]:
        return _failed(result, f"Only {n_free} boundary points above the baseline (minimum {lim['min_contour_points']}). Use a larger image of the droplet or a tighter ROI.")

    waist = _waist(umap[comp], vmap[comp])
    if waist is not None:
        warns.append(f"Profile narrows at ~{waist:.0f} px above the baseline: a droplet reflection may be included. Move the baseline to the narrowest point.")
        wu = uv[np.abs(uv[:, 1] - waist) < 1.5, 0]
        if wu.size:
            result["suggested_baseline"] = frame.to_xy([[wu.min() - 20, waist], [wu.max() + 20, waist]]).round(2).tolist()

    # Contact points
    if p.get("contact_left") is not None and p.get("contact_right") is not None:
        est_l, est_r = frame.to_uv(p["contact_left"])[0, 0], frame.to_uv(p["contact_right"])[0, 0]
        cp_source = "manual"
    else:
        band = comp & (vmap <= CUT_PX + 3)
        if not band.any():
            diags.append(_diag("contact_points", "Contact points", "not found", "fail"))
            return _failed(result, "Droplet does not reach the baseline; contact points not found.")
        est_l, est_r = float(umap[band].min()), float(umap[band].max())
        cp_source = "auto"
    base_w = est_r - est_l
    if base_w < 8:
        diags.append(_diag("contact_points", "Contact points", "implausible", "fail", note=f"Contact width {base_w:.1f} px"))
        return _failed(result, "Contact width is implausibly small; check the baseline position.")
    max_w = float(np.ptp(uv[:, 0]))
    height = float(uv[:, 1].max())
    radius = float(p.get("fit_radius_px") or np.clip(lim["fit_radius_fraction"] * max_w, 12, 600))
    result["geometry"]["fit_radius_px"] = round(radius, 1)
    mid = (est_l + est_r) / 2

    # Local polynomial tangents
    poly: dict[str, Any] = {"status": "ok", "sides": {}}
    for side, est in (("left", est_l), ("right", est_r)):
        sel = free & (np.hypot(uv[:, 0] - est, uv[:, 1]) <= radius) & ((uv[:, 0] < mid) if side == "left" else (uv[:, 0] > mid))
        if sel.sum() < lim["min_side_points"]:
            poly["status"] = "failed"
            poly["sides"][side] = {"error": f"{int(sel.sum())} points in the {side} fitting region (minimum {lim['min_side_points']})."}
            continue
        try:
            fit = g.fit_side_tangent(uv[sel], est, side, int(lim["poly_degree"]))
        except (g.GeometryError, np.linalg.LinAlgError) as exc:
            poly["status"] = "failed"
            poly["sides"][side] = {"error": str(exc)}
            continue
        poly["sides"][side] = {"angle_deg": fit.angle_deg, "rms_px": fit.rms_px, "n_points": fit.n_points,
                               "parameterisation": fit.parameterisation, "contact_uv": fit.contact_uv, "tangent_uv": fit.tangent_uv}
    if poly["status"] == "ok":
        l, r = poly["sides"]["left"]["angle_deg"], poly["sides"]["right"]["angle_deg"]
        poly.update(left_deg=l, right_deg=r, mean_deg=(l + r) / 2)
        for side in ("left", "right"):
            rms = poly["sides"][side]["rms_px"]
            diags.append(_diag(f"poly_rms_{side}", f"Local-tangent fit RMS ({side})", round(rms, 3), "warn" if rms > lim["max_poly_rms_px"] else "pass", "px",
                               f"{poly['sides'][side]['n_points']} points, {poly['sides'][side]['parameterisation']}"))
    result["methods"]["polynomial"] = poly

    # Spherical-cap circle fit
    circ: dict[str, Any] = {"status": "ok"}
    if touches["top"]:
        circ = {"status": "disabled", "error": "Apex region clipped or obstructed."}
    else:
        try:
            cf = g.fit_circle(uv[free])
            cl, cr = cf.contact_u() if cf.intersects_baseline() else (np.nan, np.nan)
            tol = max(3.0, 0.03 * base_w)
            ref_l, ref_r = ((poly["sides"]["left"]["contact_uv"][0], poly["sides"]["right"]["contact_uv"][0])
                            if poly["status"] == "ok" else (est_l, est_r))
            problems = []
            if not cf.intersects_baseline():
                problems.append("Fitted circle does not intersect the baseline.")
            if cf.rel_rms > lim["circle_max_rel_rms"]:
                problems.append(f"Residual {cf.rel_rms * 100:.2f}% of radius exceeds {lim['circle_max_rel_rms'] * 100:.2f}% (profile is not a circular cap).")
            if cf.intersects_baseline() and (abs(cl - ref_l) > tol or abs(cr - ref_r) > tol):
                problems.append("Circle/baseline intersections disagree with the observed contact points.")
            circ.update(angle_deg=cf.angle_deg(), rms_px=cf.rms, rel_rms=cf.rel_rms, centre_uv=[cf.uc, cf.vc], radius_px=cf.r,
                        centre_xy=frame.to_xy([[cf.uc, cf.vc]])[0].round(2).tolist())
            if problems:
                circ.update(status="rejected", error=" ".join(problems))
            diags.append(_diag("circle_rel_rms", "Circle-fit residual / radius", round(cf.rel_rms * 100, 3), "pass" if not problems else "warn", "%",
                               "; ".join(problems)))
        except (g.GeometryError, np.linalg.LinAlgError, ValueError) as exc:
            circ = {"status": "failed", "error": str(exc)}
    result["methods"]["circle"] = circ

    # Choose reported method
    primary = p.get("primary_method") or lim["primary_method"]
    order = ["polynomial", "circle"] if primary == "polynomial" else ["circle", "polynomial"]
    chosen = next((m for m in order if result["methods"][m]["status"] == "ok"), None)
    if chosen is None:
        reasons = [f"{m}: {result['methods'][m].get('error') or '; '.join(s.get('error', '') for s in result['methods'][m].get('sides', {}).values())}" for m in order]
        diags.append(_diag("fit", "Boundary fit", "no reliable fit", "fail"))
        return _failed(result, "No fitting method produced a reliable result. " + " | ".join(reasons))
    if chosen != primary:
        warns.append(f"Preferred method '{primary}' was not reliable; reporting '{chosen}'.")
    if chosen == "polynomial":
        left, right = poly["left_deg"], poly["right_deg"]
        cu_l, cu_r = poly["sides"]["left"]["contact_uv"][0], poly["sides"]["right"]["contact_uv"][0]
        tl, tr = poly["sides"]["left"]["tangent_uv"], poly["sides"]["right"]["tangent_uv"]
    else:
        left = right = circ["angle_deg"]
        cu_l, cu_r = g.CircleFit(*circ["centre_uv"], circ["radius_px"], circ["rms_px"]).contact_u()
        tl = _circle_tangent(circ, cu_l, "left")
        tr = _circle_tangent(circ, cu_r, "right")
    mean = (left + right) / 2
    lr = abs(left - right)
    result.update(method=("manual_corrected" if corrected else f"auto_{chosen}"), fit_method=chosen,
                  left_deg=round(left, 2), right_deg=round(right, 2), mean_deg=round(mean, 2), lr_diff_deg=round(lr, 2))
    lr_status = "fail" if lr > lim["lr_diff_fail_deg"] else "warn" if lr > lim["lr_diff_warn_deg"] else "pass"
    diags.append(_diag("lr_diff", "Left-right difference", round(lr, 2), lr_status, "deg",
                       "Large asymmetry: check baseline, specimen levelling and contact-line pinning." if lr_status != "pass" else ""))
    if lr_status == "warn":
        warns.append(f"Left and right angles differ by {lr:.1f} deg.")
    if poly.get("mean_deg") is not None and circ.get("status") == "ok":
        dis = abs(poly["mean_deg"] - circ["angle_deg"])
        diags.append(_diag("method_agreement", "Local tangent vs circle fit", round(dis, 2), "warn" if dis > lim["method_disagreement_warn_deg"] else "pass", "deg"))
        if dis > lim["method_disagreement_warn_deg"]:
            warns.append(f"Local-tangent and circle-fit means differ by {dis:.1f} deg; the droplet may not be a spherical cap.")
    diags.append(_diag("contact_points", "Contact points", cp_source, "pass", note=f"Contact width {cu_r - cu_l:.1f} px"))
    diags.append(_diag("manual_correction", "Manual correction applied", "yes" if corrected else "no", "pass"))
    diags.append(_diag("fit_method", "Reported fit method", chosen, "pass"))

    geo = result["geometry"]
    cl_xy, cr_xy = frame.to_xy([[cu_l, 0.0]])[0], frame.to_xy([[cu_r, 0.0]])[0]
    seg = max(20.0, 0.6 * min(height, radius * 2))
    geo["contact_left"], geo["contact_right"] = cl_xy.round(2).tolist(), cr_xy.round(2).tolist()
    geo["tangent_left"] = [cl_xy.round(2).tolist(), frame.to_xy([[cu_l + tl[0] * seg, tl[1] * seg]])[0].round(2).tolist()]
    geo["tangent_right"] = [cr_xy.round(2).tolist(), frame.to_xy([[cu_r + tr[0] * seg, tr[1] * seg]])[0].round(2).tolist()]
    fi = np.flatnonzero(free)  # open the arc at the excluded baseline segment so it is not drawn closed
    start = (int(np.argmax(np.diff(np.r_[fi, fi[0] + len(pts)]))) + 1) % len(fi)
    arc = pts[np.r_[fi[start:], fi[:start]]]
    geo["contour"] = arc[:: max(1, len(arc) // 600)].round(1).tolist()
    if circ.get("status") == "ok":
        geo["circle"] = {"centre": circ["centre_xy"], "radius": round(circ["radius_px"], 2)}
    geo["droplet_height_px"], geo["contact_width_px"] = round(height, 1), round(cu_r - cu_l, 1)

    result["classification"] = g.classify(mean, left, right, lim["classification_display_tolerance_deg"])
    if any(d["status"] == "fail" for d in diags):
        result["status"] = "needs_correction"
    return result


def _circle_tangent(circ: dict, cu: float, side: str) -> tuple[float, float]:
    uc, vc = circ["centre_uv"]
    radial = np.array([cu - uc, -vc])
    t = np.array([-radial[1], radial[0]])
    t = t if t[1] > 0 else -t
    t = t / np.hypot(*t)
    return float(t[0]), float(t[1])


def _manual_tangent(result: dict, p: dict, lim: dict) -> dict:
    needed = ("baseline", "contact_left", "contact_right", "tangent_left", "tangent_right")
    missing = [k for k in needed if p.get(k) is None]
    if missing:
        return _failed(result, f"Manual tangent mode requires: {', '.join(missing)}.")
    try:
        frame = g.make_frame(*p["baseline"])
        left = g.manual_tangent_angle(frame, p["contact_left"], p["tangent_left"], "left")
        right = g.manual_tangent_angle(frame, p["contact_right"], p["tangent_right"], "right")
    except g.GeometryError as exc:
        return _failed(result, str(exc))
    if frame.to_uv(p["contact_left"])[0, 0] >= frame.to_uv(p["contact_right"])[0, 0]:
        return _failed(result, "Left contact point must be left of the right contact point along the baseline.")
    for side in ("left", "right"):
        off = abs(frame.to_uv(p[f"contact_{side}"])[0, 1])
        if off > 3:
            result["warnings"].append(f"{side.capitalize()} contact point lies {off:.1f} px off the baseline.")
    mean, lr = (left + right) / 2, abs(left - right)
    result.update(method="manual_tangent", fit_method="manual_tangent", manual_correction=True,
                  left_deg=round(left, 2), right_deg=round(right, 2), mean_deg=round(mean, 2), lr_diff_deg=round(lr, 2))
    result["diagnostics"].append(_diag("fit_method", "Reported fit method", "manual tangent", "pass",
                                       note="Angles derived entirely from operator-placed points; precision depends on placement."))
    result["diagnostics"].append(_diag("lr_diff", "Left-right difference", round(lr, 2), "fail" if lr > lim["lr_diff_fail_deg"] else "warn" if lr > lim["lr_diff_warn_deg"] else "pass", "deg"))
    result["geometry"].update(
        baseline=[list(map(float, p["baseline"][0])), list(map(float, p["baseline"][1]))],
        contact_left=list(map(float, p["contact_left"])), contact_right=list(map(float, p["contact_right"])),
        tangent_left=[list(map(float, p["contact_left"])), list(map(float, p["tangent_left"]))],
        tangent_right=[list(map(float, p["contact_right"])), list(map(float, p["tangent_right"]))],
        tilt_deg=round(frame.tilt_deg, 3),
    )
    result["classification"] = g.classify(mean, left, right, lim["classification_display_tolerance_deg"])
    if any(d["status"] == "fail" for d in result["diagnostics"]):
        result["status"] = "needs_correction"
    return result
