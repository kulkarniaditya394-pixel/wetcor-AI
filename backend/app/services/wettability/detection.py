"""Sessile-drop contact-angle pipeline (OpenCV segmentation + geometric fitting).

Automatic mode is a search, not a single recipe. The image is decoded (honouring phone orientation), resized to a working
scale, and cleaned of coloured overlays; several foreground fields and baseline hypotheses are proposed (proposals.py);
each combination is measured with the same geometric fit, scored on its evidence, and the best supported one is reported.
Images may be turned by 90 degrees as a last resort. Results resting on weak evidence are returned as "needs_correction"
with the reason, and images without a measurable side-on droplet still fail with a clear message, so an angle is never
reported just because some contour exists.

Measurement: droplet component above the baseline -> sub-pixel boundary -> local rotated-frame polynomial tangent per side
and a robust spherical-cap fit -> diagnostics, warnings, classification. The input bytes and arrays are never modified.
"""
from __future__ import annotations

import copy
from typing import Any

import cv2
import numpy as np
from scipy.ndimage import map_coordinates

from app.services.wettability import geometry as g
from app.services.wettability import proposals as P

ALGORITHM_VERSION = "ca-2.0.0"
UNCERTAINTY_NOTE = (
    "Quality indicators are heuristic diagnostics of the image and fit. They are not a calibrated "
    "measurement uncertainty; repeatability must be established by repeated drops."
)
CUT_PX = 1.5  # droplet pixels must lie at least this far above the baseline
MAX_PIXELS = 50_000_000
WORK_MAX_SIDE = 1600  # larger photos are analysed at this size
WORK_MIN_SIDE = 420  # tiny images are enlarged so that sub-pixel fitting has room
GOOD_ENOUGH = 0.8  # a surface line on both sides of a well-shaped drop ends the search
MIN_ACCEPT = 0.42  # below this the best candidate is not reported as a measurement
MAX_CAP_RMS = 0.05  # circle-fit residual / radius at which a candidate loses all shape credit
MAX_NOT_CAP = 0.08  # beyond this the boundary is not a droplet at all (gravity-flattened drops stay well inside)


class ImageError(ValueError):
    pass


def decode_image(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    if not data:
        raise ImageError("Empty image.")
    # ANYCOLOR|ANYDEPTH (unlike UNCHANGED) applies the EXIF orientation that phones write
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_ANYCOLOR | cv2.IMREAD_ANYDEPTH)
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


def _refine_subpixel(img: np.ndarray, pts: np.ndarray, t: float, mode: str = "level") -> np.ndarray:
    """Move pixel contour points to the sub-pixel boundary along the local gradient: threshold crossing, or steepest edge."""
    gy, gx = np.gradient(img)
    xi, yi = pts[:, 0].astype(int), pts[:, 1].astype(int)
    grad = np.column_stack([gx[yi, xi], gy[yi, xi]])
    norm = np.hypot(grad[:, 0], grad[:, 1])
    ok = norm > 1e-6
    grad[ok] /= norm[ok, None]
    offs = np.linspace(-2.5, 2.5, 11)
    samples = pts[:, None, :] + offs[None, :, None] * grad[:, None, :]
    vals = map_coordinates(img, [samples[..., 1].ravel(), samples[..., 0].ravel()], order=1, mode="nearest").reshape(len(pts), len(offs))
    out = pts.copy()
    if mode == "edge":
        step = np.abs(np.diff(vals, axis=1))
        shift = offs[:-1][step.argmax(axis=1)] + (offs[1] - offs[0]) / 2
        out[ok] += shift[ok, None] * grad[ok]
        return out
    d = vals - t
    a, b = d[:, :-1], d[:, 1:]
    cross = (np.sign(a) != np.sign(b)) & (a != b)
    with np.errstate(divide="ignore", invalid="ignore"):
        pos = offs[:-1] + (-a / (b - a)) * (offs[1] - offs[0])
    pos = np.where(cross, pos, np.inf)
    best = np.abs(pos).argmin(axis=1)
    shift = pos[np.arange(len(pts)), best]
    ok &= np.isfinite(shift)
    out[ok] += shift[ok, None] * grad[ok]
    return out


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


def _circle_tangent(circ: dict, cu: float) -> tuple[float, float]:
    uc, vc = circ["centre_uv"]
    radial = np.array([cu - uc, -vc])
    t = np.array([-radial[1], radial[0]])
    t = t if t[1] > 0 else -t
    t = t / np.hypot(*t)
    return float(t[0]), float(t[1])


def _measure(fld: P.Field, frame: g.Frame, guess: P.Guess | None, lim: dict, p: dict) -> dict:
    """One candidate: a foreground field plus a baseline. Returns {"error": ...} or a complete measurement."""
    mask = fld.mask
    h, w = mask.shape
    m: dict[str, Any] = {"field": fld, "guess": guess, "frame": frame, "diagnostics": [], "warnings": [], "methods": {}, "geometry": {}, "error": None, "stage": 0}
    tol = guess.tolerance if guess else 1.0
    cut = max(CUT_PX, tol)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    umap = (xx - frame.origin[0]) * frame.d[0] + (yy - frame.origin[1]) * frame.d[1]
    vmap = (xx - frame.origin[0]) * frame.n[0] + (yy - frame.origin[1]) * frame.n[1]
    above = (mask & (vmap > cut)).astype(np.uint8)
    # a thin sliver of rough surface must not join the droplet to the image edge
    k = max(3, int(0.006 * max(h, w)) | 1)
    opened = cv2.morphologyEx(above, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n_cc, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    min_area = max(50, int(0.0004 * above.size))
    best, best_area = 0, 0
    for c in np.argsort(-stats[1:, cv2.CC_STAT_AREA])[:6] + 1:
        area = stats[c, cv2.CC_STAT_AREA]
        if area < min_area:
            break
        if vmap[labels == c].min() <= cut + 3 + k and area > best_area:
            best, best_area = c, area
    if best == 0:
        m["error"] = "No droplet touching the baseline was detected. Check the ROI, threshold and baseline."
        return m
    comp = labels == best
    m["stage"] = 1
    touches = {"left": comp[:, 0].any(), "right": comp[:, -1].any(), "top": comp[0, :].any()}
    if touches["left"] or touches["right"]:
        low_l, low_r = vmap[comp & (xx == 0)], vmap[comp & (xx == w - 1)]
        spans = bool(low_l.size and low_r.size and low_l.min() <= cut + 4 and low_r.min() <= cut + 4)
        m["error"] = ("Region above the baseline spans the full width near the baseline: the baseline probably lies below the specimen surface. Move it up."
                      if spans else "Droplet is clipped by the left/right image or ROI border; contact points cannot be located.")
        return m
    needle = P.needle_end(comp)

    contours, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    raw = max(contours, key=len)[:, 0, :].astype(float)
    pts = _refine_subpixel(fld.image, raw, fld.threshold, fld.refine)
    uv = frame.to_uv(pts)
    on_body = raw[:, 1] > needle + 2 if needle is not None else np.ones(len(raw), bool)
    band = comp & (vmap <= cut + 3 + k)
    if p.get("contact_left") is not None and p.get("contact_right") is not None:
        est_l, est_r = frame.to_uv(p["contact_left"])[0, 0], frame.to_uv(p["contact_right"])[0, 0]
        cp_source = "manual"
    else:
        if not band.any():
            m["error"] = "Droplet does not reach the baseline; contact points not found."
            return m
        est_l, est_r = float(umap[band].min()), float(umap[band].max())
        cp_source = "auto"
    base_w = est_r - est_l
    if base_w < max(8, 0.04 * min(h, w)):
        m["error"] = "Contact width is implausibly small: use a closer image of the droplet, or check the baseline position."
        return m
    exclude = max(float(lim["exclude_px"]), cut * 1.3, 0.012 * base_w)
    free = (uv[:, 1] > exclude) & on_body
    n_free = int(free.sum())
    if n_free < lim["min_contour_points"]:
        m["error"] = f"Only {n_free} boundary points above the baseline (minimum {lim['min_contour_points']}). Use a larger image of the droplet or a tighter ROI."
        m["diagnostics"].append(_diag("contour_points", "Boundary points above baseline", n_free, "fail"))
        return m
    m["stage"] = 2
    m["diagnostics"].append(_diag("contour_points", "Boundary points above baseline", n_free, "pass"))

    waist = _waist(umap[comp], vmap[comp])
    if waist is not None and (guess is None or guess.kind != "mirror"):
        m["warnings"].append(f"Profile narrows at ~{waist:.0f} px above the baseline: a droplet reflection may be included. Move the baseline to the narrowest point.")
        wu = uv[np.abs(uv[:, 1] - waist) < 1.5, 0]
        if wu.size:
            m["suggested_baseline"] = frame.to_xy([[wu.min() - 20, waist], [wu.max() + 20, waist]]).round(2).tolist()

    return _fit(m, pts, uv, free, est_l, est_r, cp_source, top_touch=bool(touches["top"]), needle=needle is not None, lim=lim, p=p)


def _measure_arc(arc: P.Arc, fld: P.Field, frame: g.Frame, guess: P.Guess, lim: dict, p: dict) -> dict:
    """One candidate from a traced outline: no segmentation, the boundary points are already known."""
    m: dict[str, Any] = {"field": fld, "guess": guess, "frame": frame, "diagnostics": [], "warnings": [], "methods": {}, "geometry": {}, "error": None, "stage": 1, "arc": arc}
    uv = frame.to_uv(arc.points)
    try:
        cf, _ = g.fit_circle_robust(uv[uv[:, 1] > 0])
    except (g.GeometryError, ValueError, np.linalg.LinAlgError):
        cf = None
    if cf is None or not cf.intersects_baseline():
        m["error"] = "The drop outline does not meet the baseline."
        return m
    est_l, est_r = cf.contact_u()
    ends = frame.to_xy([[est_l, 0.0], [est_r, 0.0]])
    if ends[:, 0].min() < 0 or ends[:, 0].max() >= fld.image.shape[1]:
        m["error"] = "Droplet is clipped by the left/right image or ROI border; contact points cannot be located."
        return m
    free = uv[:, 1] > max(float(lim["exclude_px"]), 0.02 * (est_r - est_l))
    n_free = int(free.sum())
    if n_free < lim["min_contour_points"]:
        m["error"] = f"Only {n_free} boundary points above the baseline (minimum {lim['min_contour_points']})."
        return m
    m["stage"] = 2
    m["diagnostics"].append(_diag("contour_points", "Boundary points above baseline", n_free, "pass"))
    rays = float((cf.vc + cf.r * np.cos(np.radians(np.arange(720) / 2)) > 0).sum())
    m["fill"] = min(1.0, float((uv[:, 1] > 0).sum()) / max(rays, 1.0))
    return _fit(m, arc.points, uv, free, est_l, est_r, "from the outline", top_touch=False, needle=False, lim=lim, p=p, prefer_circle=True)


def _fit(m: dict, pts: np.ndarray, uv: np.ndarray, free: np.ndarray, est_l: float, est_r: float, cp_source: str, *, top_touch: bool, needle: bool, lim: dict, p: dict, prefer_circle: bool = False) -> dict:
    """Shared by both candidate kinds: local tangents and spherical-cap fit on boundary points in the baseline frame."""
    frame = m["frame"]
    base_w = est_r - est_l
    max_w = float(np.ptp(uv[free, 0]))
    height = float(uv[free, 1].max())
    radius = float(p.get("fit_radius_px") or np.clip(lim["fit_radius_fraction"] * max_w, 12, 600))
    mid = (est_l + est_r) / 2

    # Local polynomial tangents (second pass centred on the refined contact point)
    poly: dict[str, Any] = {"status": "ok", "sides": {}}
    for side, est in (("left", est_l), ("right", est_r)):
        fit = None
        err = None
        centre = est
        for _ in range(2):
            sel = free & (np.hypot(uv[:, 0] - centre, uv[:, 1]) <= radius) & ((uv[:, 0] < mid) if side == "left" else (uv[:, 0] > mid))
            if sel.sum() < lim["min_side_points"]:
                err = f"{int(sel.sum())} points in the {side} fitting region (minimum {lim['min_side_points']})."
                break
            try:
                fit = g.fit_side_tangent(uv[sel], centre, side, int(lim["poly_degree"]))
                err = None
            except (g.GeometryError, np.linalg.LinAlgError) as exc:
                err = str(exc)
                break
            centre = fit.contact_uv[0]
        if err or fit is None:
            poly["status"] = "failed"
            poly["sides"][side] = {"error": err or "no fit"}
            continue
        poly["sides"][side] = {"angle_deg": fit.angle_deg, "rms_px": fit.rms_px, "n_points": fit.n_points, "parameterisation": fit.parameterisation,
                               "contact_uv": fit.contact_uv, "tangent_uv": fit.tangent_uv}
    if poly["status"] == "ok":
        left, right = poly["sides"]["left"]["angle_deg"], poly["sides"]["right"]["angle_deg"]
        poly.update(left_deg=left, right_deg=right, mean_deg=(left + right) / 2)
        for side in ("left", "right"):
            rms = poly["sides"][side]["rms_px"]
            m["diagnostics"].append(_diag(f"poly_rms_{side}", f"Local-tangent fit RMS ({side})", round(rms, 3), "warn" if rms > lim["max_poly_rms_px"] else "pass", "px",
                                          f"{poly['sides'][side]['n_points']} points, {poly['sides'][side]['parameterisation']}"))
    m["methods"]["polynomial"] = poly

    # Spherical-cap fit
    circ: dict[str, Any] = {"status": "ok"}
    try:
        cf, inliers = g.fit_circle_robust(uv[free])
        cl, cr = cf.contact_u() if cf.intersects_baseline() else (np.nan, np.nan)
        tol_c = max(3.0, 0.06 * base_w)
        ref_l, ref_r = ((poly["sides"]["left"]["contact_uv"][0], poly["sides"]["right"]["contact_uv"][0]) if poly["status"] == "ok" else (est_l, est_r))
        problems = []
        if not cf.intersects_baseline():
            problems.append("Fitted circle does not intersect the baseline.")
        if cf.rel_rms > lim["circle_max_rel_rms"]:
            problems.append(f"Residual {cf.rel_rms * 100:.2f}% of radius exceeds {lim['circle_max_rel_rms'] * 100:.2f}% (profile is not a circular cap).")
        if cf.intersects_baseline() and (abs(cl - ref_l) > tol_c or abs(cr - ref_r) > tol_c):
            problems.append("Circle/baseline intersections disagree with the observed contact points.")
        circ.update(angle_deg=cf.angle_deg(), rms_px=cf.rms, rel_rms=cf.rel_rms, centre_uv=[cf.uc, cf.vc], radius_px=cf.r, inlier_fraction=inliers,
                    centre_xy=frame.to_xy([[cf.uc, cf.vc]])[0].round(2).tolist())
        if problems:
            circ.update(status="rejected", error=" ".join(problems))
        m["diagnostics"].append(_diag("circle_rel_rms", "Circle-fit residual / radius", round(cf.rel_rms * 100, 3), "pass" if not problems else "warn", "%", "; ".join(problems)))
    except (g.GeometryError, np.linalg.LinAlgError, ValueError) as exc:
        circ = {"status": "failed", "error": str(exc)}
    m["methods"]["circle"] = circ
    if circ.get("rel_rms", 0) > MAX_NOT_CAP or circ.get("radius_px", 0) > 3 * base_w:
        m["error"] = "The boundary found here is not shaped like a droplet."
        return m

    # Choose the reported method
    # a traced outline is thin near the contact line, so the whole-profile fit is the sound one whatever the default method
    primary = "circle" if prefer_circle else p.get("primary_method") or lim["primary_method"]
    order = ["polynomial", "circle"] if primary == "polynomial" else ["circle", "polynomial"]
    chosen = next((x for x in order if m["methods"][x]["status"] == "ok"), None)
    if chosen == "polynomial" and circ.get("status") == "ok" and not p.get("primary_method"):
        worst = max(poly["sides"]["left"]["rms_px"], poly["sides"]["right"]["rms_px"])
        if worst > lim["max_poly_rms_px"] and abs(poly["mean_deg"] - circ["angle_deg"]) > lim["method_disagreement_warn_deg"]:
            chosen = "circle"  # a rough boundary near the contact line: the whole-profile fit is the steadier one
            m["warnings"].append("Boundary near the contact line is rough; the spherical-cap fit is reported instead of the local tangent.")
    if chosen is None:
        reasons = [f"{x}: {m['methods'][x].get('error') or '; '.join(s.get('error', '') for s in m['methods'][x].get('sides', {}).values())}" for x in order]
        m["error"] = "No fitting method produced a reliable result. " + " | ".join(reasons)
        return m
    if chosen != primary and "Boundary near" not in " ".join(m["warnings"]) and not prefer_circle:
        m["warnings"].append(f"Preferred method '{primary}' was not reliable; reporting '{chosen}'.")
    if chosen == "polynomial":
        left, right = poly["left_deg"], poly["right_deg"]
        cu_l, cu_r = poly["sides"]["left"]["contact_uv"][0], poly["sides"]["right"]["contact_uv"][0]
        tl, tr = poly["sides"]["left"]["tangent_uv"], poly["sides"]["right"]["tangent_uv"]
    else:
        left = right = circ["angle_deg"]
        cu_l, cu_r = g.CircleFit(*circ["centre_uv"], circ["radius_px"], circ["rms_px"]).contact_u()
        tl, tr = _circle_tangent(circ, cu_l), _circle_tangent(circ, cu_r)
    if not (2 < left < 178 and 2 < right < 178):
        m["error"] = "Fitted angles are outside the physically measurable range."
        return m
    m["stage"] = 3
    fi = np.flatnonzero(free)  # open the arc at the excluded baseline segment so it is not drawn closed
    start = (int(np.argmax(np.diff(np.r_[fi, fi[0] + len(pts)]))) + 1) % len(fi)
    arc = pts[np.r_[fi[start:], fi[:start]]]
    cl_xy, cr_xy = frame.to_xy([[cu_l, 0.0]])[0], frame.to_xy([[cu_r, 0.0]])[0]
    seg = max(20.0, 0.6 * min(height, radius * 2))
    geo = m["geometry"]
    geo["fit_radius_px"], geo["droplet_height_px"], geo["contact_width_px"] = radius, height, cu_r - cu_l
    geo["contact_left"], geo["contact_right"] = cl_xy, cr_xy
    geo["tangent_left"] = [cl_xy, frame.to_xy([[cu_l + tl[0] * seg, tl[1] * seg]])[0]]
    geo["tangent_right"] = [cr_xy, frame.to_xy([[cu_r + tr[0] * seg, tr[1] * seg]])[0]]
    geo["contour"] = arc[:: max(1, len(arc) // 600)]
    if circ.get("status") == "ok":
        geo["circle"] = {"centre": np.array(circ["centre_xy"]), "radius": circ["radius_px"]}
    m.update(left=left, right=right, chosen=chosen, cp_source=cp_source, needle=needle, top_touch=top_touch, n_free=int(free.sum()), width=cu_r - cu_l, height=height)
    m["gap"] = max(0.0, float(uv[free, 1].min()) / height)  # share of the drop height with no visible boundary at the base
    if m["gap"] > 0.25:
        m["warnings"].append(f"The lowest {m['gap'] * 100:.0f}% of the drop outline is not visible, so the angle is extrapolated from the upper part.")
    m["score"] = _score(m, lim)
    return m


def _score(m: dict, lim: dict) -> float:
    """Evidence for a candidate, 0..1: how the baseline was found, and how well the boundary behaves like a droplet."""
    guess: P.Guess | None = m["guess"]
    base = guess.confidence if guess else 0.9
    if m.get("arc") is not None:
        # the more of the circle is clearly seen, the less likely it is something else
        base *= float(np.clip(0.75 + m["arc"].span_deg / 600, 0.8, 1.0)) * (0.82 + 0.18 * m["arc"].top_fill) * (0.8 + 0.2 * m["fill"])
    circ, poly = m["methods"]["circle"], m["methods"]["polynomial"]
    fit = 1.0
    rel = circ.get("rel_rms")
    if rel is None:
        fit -= 0.25
    else:
        fit -= min(rel / MAX_CAP_RMS, 1.0) * 0.45
        fit -= (1 - circ.get("inlier_fraction", 1.0)) * 0.5
        if circ.get("status") != "ok":
            fit -= 0.05
    fit -= min(abs(m["left"] - m["right"]) / 18, 1.0) * 0.2
    if poly.get("mean_deg") is not None and circ.get("angle_deg") is not None:
        fit -= min(abs(poly["mean_deg"] - circ["angle_deg"]) / 18, 1.0) * 0.2
    return max(0.0, 0.55 * base + 0.45 * max(fit, 0.0) - 0.6 * m["gap"])


def _scaled(p: dict, f: float, x0: int, y0: int) -> dict:
    """User coordinates (full image) to working coordinates."""
    out = dict(p)
    for k in ("contact_left", "contact_right"):
        if out.get(k) is not None:
            out[k] = [(out[k][0] - x0) * f, (out[k][1] - y0) * f]
    if out.get("baseline") is not None:
        out["baseline"] = [[(q[0] - x0) * f, (q[1] - y0) * f] for q in out["baseline"]]
    if out.get("fit_radius_px"):
        out["fit_radius_px"] = out["fit_radius_px"] * f
    return out


def _penalise(m: dict, arcs: list[P.Arc]) -> None:
    """A baseline with a drop outline visibly continuing underneath it cuts through the drop."""
    if m.get("score") is None or not arcs:
        return
    frame = m["frame"]
    p1, p2 = frame.to_xy([[0.0, 0.0], [100.0, 0.0]])
    a = (p2[1] - p1[1]) / (p2[0] - p1[0])
    mid = (np.asarray(m["geometry"]["contact_left"]) + np.asarray(m["geometry"]["contact_right"])) / 2
    near = [arc for arc in arcs if np.hypot(arc.cx - mid[0], arc.cy - mid[1]) < arc.r]
    m["continues"] = min((P.continues_below(arc, a, p1[1] - a * p1[0]) for arc in near), default=0.0)
    if m["continues"] > 0.2:
        m["score"] *= 1 - min(1.0, 1.6 * m["continues"])


def _line_frame(b: P.Guess, w: int) -> g.Frame | None:
    try:
        return g.make_frame((0.0, b.b), (w - 1.0, b.a * (w - 1.0) + b.b))
    except g.GeometryError:
        return None


def _search(bgr: np.ndarray, gray: np.ndarray, p: dict, lim: dict) -> tuple[dict | None, list[dict], P.Guess | None]:
    """Try field/baseline combinations until one is convincing. Returns (best, all, first baseline guess)."""
    rng = np.random.default_rng(12345)  # fixed: the same image always gives the same result
    tried: list[dict] = []
    first_guess: P.Guess | None = None
    user_seg = p.get("threshold") is not None or p.get("polarity", "auto") != "auto"
    automatic = not p.get("baseline") and not user_seg
    flds = [P.grey_field(gray, p.get("threshold"), p.get("polarity", "auto"))] if user_seg else P.fields(bgr, gray)
    channels = P.outline_channels(bgr)
    arcs = [a for c in P.find_circles(gray, rng) if (a := P.trace_arc(channels, *c)) is not None] if automatic else []
    across = P.global_lines(channels) if not p.get("baseline") else []
    # a patchy arc whose top lies below the plate's surface is plate texture, not a drop
    arcs = [a for a in arcs if a.top_fill >= 0.8 or not any(a.cy - a.r > b.a * a.cx + b.b + 0.05 * a.r for b in across)]
    hough = P.hough_lines(gray) if not p.get("baseline") else []
    surfaces: list[P.Guess] = across + hough
    w = gray.shape[1]
    for fld in flds:
        if fld.contrast < lim["fail_contrast_levels"] and fld.name == "grey level":
            tried.append({"error": "Contrast is too low for reliable segmentation of the grey-level image.", "stage": 0, "field": fld})
            continue
        if p.get("baseline"):
            try:
                frames = [(g.make_frame(*p["baseline"]), None)]
            except g.GeometryError as exc:
                return None, [{"error": str(exc), "stage": 0, "fatal": True}], None
        else:
            guesses = P.baselines(fld.mask, gray, rng)
            surfaces += [b for b in guesses if b.kind == "surface"]
            frames = [(f, b) for b in across + guesses + hough if (f := _line_frame(b, w)) is not None]
            first_guess = first_guess or (frames[0][1] if frames else None)
        for frame, guess in frames:
            m = _measure(fld, frame, guess, lim, p)
            _penalise(m, arcs)
            tried.append(m)
            if m.get("score", 0) >= GOOD_ENOUGH and guess is not None and guess.kind == "surface":
                return m, tried, first_guess
    for arc in arcs:
        outline = P.Field("drop outline", gray.astype(np.float32), 0.0, None, "any", arc.strength, "edge")
        for b in P.arc_lines(arc, surfaces):
            frame = _line_frame(b, w)
            if frame is None:
                continue
            first_guess = first_guess or b
            m = _measure_arc(arc, outline, frame, b, lim, p)
            _penalise(m, arcs)
            tried.append(m)
            if b.kind == "surface step" and m.get("score") is not None and m["gap"] < 0.25:
                break  # lines are in order of trust: a real surface the outline reaches beats where the outline happens to fade
    done = [m for m in tried if m.get("score") is not None]
    return (max(done, key=lambda m: m["score"]) if done else None), tried, first_guess


def _map_geometry(geo: dict, fn, s: float) -> dict:
    out: dict[str, Any] = {}
    for k, v in geo.items():
        if k in ("contact_left", "contact_right"):
            out[k] = fn(np.array(v)[None, :])[0].round(2).tolist()
        elif k in ("tangent_left", "tangent_right"):
            out[k] = fn(np.array(v)).round(2).tolist()
        elif k == "contour":
            out[k] = fn(np.array(v)).round(1).tolist()
        elif k == "circle":
            out[k] = {"centre": fn(np.array(v["centre"])[None, :])[0].round(2).tolist(), "radius": round(float(v["radius"]) / s, 2)}
        else:
            out[k] = round(float(v) / s, 1)
    return out


def analyze(data: bytes, params: dict | None = None, limits: dict | None = None) -> dict:
    from app.core.defaults import defaults

    p = params or {}
    lim = {**defaults()["wettability"], **(limits or {})}
    result: dict[str, Any] = {
        "status": "ok", "method": None, "algorithm_version": ALGORITHM_VERSION,
        "left_deg": None, "right_deg": None, "mean_deg": None, "lr_diff_deg": None, "classification": None,
        "methods": {}, "geometry": {}, "diagnostics": [], "warnings": [], "errors": [],
        "image": None, "params": dict(p), "limits": lim, "uncertainty_note": UNCERTAINTY_NOTE,
        "manual_correction": False, "suggested_baseline": None, "detection": None,
    }
    diags, warns = result["diagnostics"], result["warnings"]

    def failed(message: str) -> dict:
        result["errors"].append(message)
        result["status"] = "failed"
        return result

    try:
        bgr, gray = decode_image(data)
    except ImageError as exc:
        return failed(str(exc))
    H, W = gray.shape
    result["image"] = {"width": W, "height": H}

    roi = p.get("roi")
    if roi:
        x0, y0 = max(0, int(roi[0])), max(0, int(roi[1]))
        x1, y1 = min(W, int(roi[0] + roi[2])), min(H, int(roi[1] + roi[3]))
        if x1 - x0 < 32 or y1 - y0 < 32:
            return failed("Region of interest is smaller than 32x32 px.")
    else:
        x0, y0, x1, y1 = 0, 0, W, H
    result["geometry"]["roi"] = [x0, y0, x1 - x0, y1 - y0]
    sub, sub_bgr = gray[y0:y1, x0:x1], bgr[y0:y1, x0:x1]

    clip = float(np.mean((sub <= 0) | (sub >= 255)))
    diags.append(_diag("clipping", "Saturated pixels", round(clip * 100, 2), "warn" if clip > lim["clip_fraction_warn"] else "pass", "%",
                       "Over- or under-exposure shifts the detected edge." if clip > lim["clip_fraction_warn"] else ""))

    if p.get("mode") == "manual_tangent":
        return _manual_tangent(result, p, lim)

    corrected = any(p.get(k) is not None for k in ("baseline", "contact_left", "contact_right", "threshold", "fit_radius_px")) or p.get("polarity", "auto") != "auto"
    result["manual_correction"] = corrected

    # Working scale
    side_max, side_min = max(sub.shape), min(sub.shape)
    f = WORK_MAX_SIDE / side_max if side_max > WORK_MAX_SIDE else min(3.0, WORK_MIN_SIDE / side_min) if side_min < WORK_MIN_SIDE else 1.0
    if f != 1.0:
        size = (int(round(sub.shape[1] * f)), int(round(sub.shape[0] * f)))
        interp = cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC
        work, work_bgr = cv2.resize(sub, size, interpolation=interp), cv2.resize(sub_bgr, size, interpolation=interp)
    else:
        work, work_bgr = sub, sub_bgr
    work_bgr, work, painted = P.remove_colour_overlay(work_bgr, work)
    if painted:
        warns.append("Coloured marks on the image (labels or lines from other software) were ignored for the analysis.")

    q = _scaled(p, f, x0, y0)
    best, tried, first = _search(work_bgr, work, q, lim)
    rotation = 0
    if best is None and not p.get("baseline") and not any(m.get("fatal") for m in tried):
        for k in (1, 3, 2):  # sideways or upside-down photo with no orientation tag
            cand, more, _ = _search(np.rot90(work_bgr, k).copy(), np.rot90(work, k).copy(), {**q, "contact_left": None, "contact_right": None}, lim)
            if cand is not None and cand["score"] >= 0.85 and cand.get("arc") is not None and cand["guess"].kind == "surface step" and cand["arc"].top_fill >= 0.8:
                best, rotation = cand, k
                tried += more
                break

    def to_image(pts: np.ndarray) -> np.ndarray:
        """Working coordinates (possibly rotated) back to full-image coordinates."""
        pts = np.asarray(pts, dtype=float)
        hw, ww = work.shape
        if rotation == 1:
            pts = np.column_stack([ww - 1 - pts[:, 1], pts[:, 0]])
        elif rotation == 2:
            pts = np.column_stack([ww - 1 - pts[:, 0], hw - 1 - pts[:, 1]])
        elif rotation == 3:
            pts = np.column_stack([pts[:, 1], hw - 1 - pts[:, 0]])
        return pts / f + np.array([x0, y0], dtype=float)

    if best is None or best["score"] < MIN_ACCEPT:
        reached = sorted((m for m in tried if m.get("error")), key=lambda m: -m.get("stage", 0))
        message = reached[0]["error"] if reached and reached[0].get("stage", 0) >= 1 else None
        if any(m.get("fatal") for m in tried):
            return failed(reached[0]["error"])
        if first is not None:
            w_ = work.shape[1] - 1.0
            result["geometry"]["baseline"] = to_image(np.array([[0.0, first.b], [w_, first.a * w_ + first.b]])).round(2).tolist()
        low = [m for m in tried if m.get("field") is not None and m["field"].name == "grey level" and "Contrast" in (m.get("error") or "")]
        if low and message is None:
            diags.append(_diag("contrast", "Droplet/background contrast", round(low[0]["field"].contrast, 1), "fail", "grey levels"))
            return failed("Contrast is too low for reliable automatic segmentation. Improve back-lighting, adjust the threshold, or use manual tangent mode.")
        hint = "Use a side-on photo with the droplet and surface in view, or drag the baseline onto the surface and re-analyse."
        return failed(f"{message} {hint}" if message else f"No measurable droplet profile found. {hint}")

    m = best
    fld, frame, guess = m["field"], m["frame"], m["guess"]
    frame_xy = to_image(frame.to_xy(np.array([[0.0, 0.0], [100.0, 0.0]])))
    img_frame = g.make_frame(frame_xy[0], frame_xy[1]) if rotation == 0 else None
    corners = np.array([[0, 0], [work.shape[1], 0], [0, work.shape[0]], [work.shape[1], work.shape[0]]], dtype=float)
    cu = frame.to_uv(corners)[:, 0]
    geo = result["geometry"]
    geo["baseline"] = to_image(frame.to_xy([[cu.min(), 0], [cu.max(), 0]])).round(2).tolist()
    geo["baseline_points"] = frame_xy.round(2).tolist()
    geo["tilt_deg"] = round(img_frame.tilt_deg if img_frame else frame.tilt_deg, 3)
    geo.update(_map_geometry(m["geometry"], to_image, f))
    if m.get("suggested_baseline") and rotation == 0:
        result["suggested_baseline"] = to_image(np.array(m["suggested_baseline"])).round(2).tolist()

    left, right = float(m["left"]), float(m["right"])
    mean, lr = (left + right) / 2, abs(left - right)
    result["methods"] = copy.deepcopy(m["methods"])
    if result["methods"]["circle"].get("radius_px"):
        result["methods"]["circle"]["radius_px"] = result["methods"]["circle"]["radius_px"] / f
        result["methods"]["circle"]["rms_px"] = result["methods"]["circle"]["rms_px"] / f
        result["methods"]["circle"]["centre_xy"] = to_image(np.array(result["methods"]["circle"]["centre_xy"])[None, :])[0].round(2).tolist()
    result.update(method=("manual_corrected" if corrected else f"auto_{m['chosen']}"), fit_method=m["chosen"],
                  left_deg=round(left, 2), right_deg=round(right, 2), mean_deg=round(mean, 2), lr_diff_deg=round(lr, 2))
    warns.extend(m["warnings"])

    c_status = "warn" if fld.name == "grey level" and fld.contrast < lim["min_contrast_levels"] else "pass"
    diags.append(_diag("contrast", "Droplet/background contrast", round(fld.contrast, 1), c_status, "grey levels" if fld.name == "grey level" else "field units"))
    if c_status == "warn":
        warns.append("Low contrast: the detected boundary may be biased. Verify the overlay.")
    diags.append(_diag("baseline", "Baseline", "manual" if guess is None else f"auto ({guess.kind.replace('_', ' ')})", "pass", note=f"{guess.note if guess else 'Placed by the operator'}; tilt {geo['tilt_deg']:.2f} deg"))
    diags.append(_diag("segmentation", "Droplet found by", fld.name, "pass", note=f"{len(tried)} candidate(s) evaluated"))
    diags.extend(m["diagnostics"])
    poly, circ = m["methods"]["polynomial"], m["methods"]["circle"]
    lr_status = "fail" if lr > lim["lr_diff_fail_deg"] else "warn" if lr > lim["lr_diff_warn_deg"] else "pass"
    diags.append(_diag("lr_diff", "Left-right difference", round(lr, 2), lr_status, "deg", "Large asymmetry: check baseline, specimen levelling and contact-line pinning." if lr_status != "pass" else ""))
    if lr_status == "warn":
        warns.append(f"Left and right angles differ by {lr:.1f} deg.")
    if poly.get("mean_deg") is not None and circ.get("status") == "ok":
        dis = abs(poly["mean_deg"] - circ["angle_deg"])
        diags.append(_diag("method_agreement", "Local tangent vs circle fit", round(dis, 2), "warn" if dis > lim["method_disagreement_warn_deg"] else "pass", "deg"))
        if dis > lim["method_disagreement_warn_deg"]:
            warns.append(f"Local-tangent and circle-fit means differ by {dis:.1f} deg; the droplet may not be a spherical cap.")
    diags.append(_diag("contact_points", "Contact points", m["cp_source"], "pass", note=f"Contact width {m['width'] / f:.1f} px"))
    diags.append(_diag("manual_correction", "Manual correction applied", "yes" if corrected else "no", "pass"))
    diags.append(_diag("fit_method", "Reported fit method", m["chosen"], "pass"))
    if m["top_touch"]:
        warns.append("Droplet region touches the top of the image/ROI (clipped apex or dispensing needle); needle pixels were ignored in the fit.")
    if rotation:
        warns.append(f"The image was analysed turned by {rotation * 90} degrees because no surface was found the right way up.")

    level = "high" if m["score"] >= 0.72 else "medium" if m["score"] >= 0.58 else "low"
    if level == "high" and guess is not None and guess.kind in ("outline ends", "level through outline end", "mirror", "flat_bottom", "hough"):
        level = "medium"  # no surface was actually seen on both sides of the drop
    if level == "high" and m.get("arc") is not None and m["arc"].top_fill < 0.8:
        level = "medium"
    result["detection"] = {"strategy": f"{fld.name} + {guess.kind.replace('_', ' ') if guess else 'manual baseline'}", "evidence": level, "score": round(float(m["score"]), 3), "candidates": len(tried), "scale": round(float(f), 3)}
    diags.append(_diag("evidence", "Detection evidence", level, "pass" if level != "low" else "fail", note="How strongly the image supports this baseline and boundary. A heuristic, not an uncertainty."))
    if level == "low":
        warns.append("Automatic detection is uncertain on this image. Check the overlay; drag the baseline onto the surface if it is off.")
    elif level == "medium":
        warns.append("Part of the drop outline or surface is unclear in this image. Confirm that the overlay sits on the drop and the surface.")

    result["classification"] = g.classify(mean, left, right, lim["classification_display_tolerance_deg"])
    if any(d["status"] == "fail" for d in diags):
        result["status"] = "needs_correction"
    return result


def _manual_tangent(result: dict, p: dict, lim: dict) -> dict:
    needed = ("baseline", "contact_left", "contact_right", "tangent_left", "tangent_right")
    missing = [k for k in needed if p.get(k) is None]
    if missing:
        result["errors"].append(f"Manual tangent mode requires: {', '.join(missing)}.")
        result["status"] = "failed"
        return result
    try:
        frame = g.make_frame(*p["baseline"])
        left = g.manual_tangent_angle(frame, p["contact_left"], p["tangent_left"], "left")
        right = g.manual_tangent_angle(frame, p["contact_right"], p["tangent_right"], "right")
    except g.GeometryError as exc:
        result["errors"].append(str(exc))
        result["status"] = "failed"
        return result
    if frame.to_uv(p["contact_left"])[0, 0] >= frame.to_uv(p["contact_right"])[0, 0]:
        result["errors"].append("Left contact point must be left of the right contact point along the baseline.")
        result["status"] = "failed"
        return result
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
