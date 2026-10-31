"""Candidate generation for automatic droplet detection on imperfect images.

Real photographs differ from ideal back-lit silhouettes: vignetted or coloured backgrounds, transparent drops with
bright interiors, mirror reflections on polished metal, rough or tilted surfaces, dispensing needles, overlay text.
No single recipe survives that, so this module proposes several foreground "fields" and several baseline hypotheses,
and detection.py measures each combination and keeps the best supported one.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import cv2
import numpy as np
from scipy.ndimage import map_coordinates

from app.services.wettability.geometry import fit_circle


MIN_ARC_DEG = 80  # shorter arcs fit too many things that are not drops


@dataclass
class Field:
    name: str
    image: np.ndarray  # float32 scalar field used for sub-pixel boundary location
    threshold: float
    mask: np.ndarray  # bool, droplet/substrate foreground
    polarity: str
    contrast: float
    refine: str = "level"  # "level": threshold crossing; "edge": strongest gradient


@dataclass
class Guess:
    kind: str  # surface | mirror | flat_bottom | hough
    a: float  # y = a x + b in working coordinates
    b: float
    confidence: float
    tolerance: float  # px of surface roughness around the line
    note: str


@dataclass
class Arc:
    cx: float
    cy: float
    r: float
    points: np.ndarray  # every boundary point that fits the outline, ordered left, over the top, to the right
    ends: np.ndarray  # where the continuous part of the outline stops, left then right
    span_deg: float
    strength: float
    step: Guess | None = None  # the surface beside the drop, when one is visible
    top_fill: float = 0.0  # share of the top 120 degrees of the circle with a clear outline


def remove_colour_overlay(bgr: np.ndarray, gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """Goniometer screenshots carry coloured labels and lines on a grey image: paint them out of the working copy."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    sat, val = hsv[..., 1], hsv[..., 2]
    mask = (sat > 90) & (val > 70)
    frac = float(mask.mean())
    if frac == 0 or frac > 0.04 or np.median(sat) > 25:
        return bgr, gray, 0
    m = cv2.dilate(mask.astype(np.uint8) * 255, np.ones((5, 5), np.uint8))
    out = cv2.inpaint(bgr, m, 4, cv2.INPAINT_TELEA)
    return out, cv2.cvtColor(out, cv2.COLOR_BGR2GRAY), int(mask.sum())


def _clean(mask: np.ndarray) -> np.ndarray:
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= max(20, 0.0002 * m.size)
    return keep[labels]


def grey_field(gray: np.ndarray, threshold: float | None = None, polarity: str = "auto") -> Field:
    """Global threshold: ideal for back-lit silhouettes."""
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    otsu, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = float(threshold) if threshold is not None else float(otsu)
    if polarity == "auto":
        polarity = "dark_drop" if np.median(blur[:2, :]) > t else "light_drop"
    mask = (blur < t) if polarity == "dark_drop" else (blur > t)
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    fg, bg = blur[mask], blur[~mask]
    contrast = float(abs(bg.mean() - fg.mean())) if fg.size and bg.size else 0.0
    return Field("grey level", cv2.GaussianBlur(gray.astype(np.float32), (5, 5), 0), t, mask, polarity, contrast)


def _terms(x: np.ndarray, y: np.ndarray, order: int = 3) -> np.ndarray:
    return np.stack([x**i * y**j for i in range(order + 1) for j in range(order + 1 - i)], axis=-1)


def background_field(bgr: np.ndarray) -> Field | None:
    """Colour distance from a smooth background model: handles vignettes, gradients, colour and either polarity."""
    h, w = bgr.shape[:2]
    sw, sh = 96, max(24, int(96 * h / w))
    lab = cv2.cvtColor(cv2.resize(bgr, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2LAB).astype(np.float32).reshape(-1, 3)
    ys, xs = np.mgrid[0:sh, 0:sw]
    x, y = (xs.ravel() / (sw - 1) * 2 - 1).astype(np.float32), (ys.ravel() / (sh - 1) * 2 - 1).astype(np.float32)
    A = _terms(x, y)
    seed = (y < -0.7) | ((np.abs(x) > 0.84) & (y < 0.0))
    sol = None
    for _ in range(5):
        if seed.sum() < 40:
            return None
        sol, *_ = np.linalg.lstsq(A[seed], lab[seed], rcond=None)
        res = np.linalg.norm(lab - A @ sol, axis=1)
        sigma = 1.4826 * float(np.median(res[seed]))
        seed = res < max(5.0, 2.5 * sigma)
    fh, fw = max(h // 4, 8), max(w // 4, 8)
    gy, gx = np.mgrid[0:fh, 0:fw]
    model = (_terms((gx.ravel() / (fw - 1) * 2 - 1).astype(np.float32), (gy.ravel() / (fh - 1) * 2 - 1).astype(np.float32)) @ sol).reshape(fh, fw, 3).astype(np.float32)
    model = cv2.resize(model, (w, h), interpolation=cv2.INTER_LINEAR)
    lab_full = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    dist = np.linalg.norm(lab_full - model, axis=2)
    top = float(np.percentile(dist, 99.5))
    if top < 8:
        return None
    t8, _ = cv2.threshold(np.clip(dist / top * 255, 0, 255).astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    t = max(t8 / 255 * top, 6.0)
    mask = _clean(dist > t)
    fg, bg = dist[mask], dist[~mask]
    if not fg.size or not bg.size:
        return None
    return Field("background model", dist, t, mask, "any", float(fg.mean() - bg.mean()))


def edge_field(gray: np.ndarray) -> Field | None:
    """Region enclosed by strong edges, seen from the top of the image: for transparent drops with a thin visible rim."""
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (0, 0), 1.5)
    hi, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(blur, max(10, 0.3 * hi), max(30, 0.7 * hi))
    if edges.mean() < 0.2:
        return None
    k = max(3, int(0.006 * max(h, w)) | 1)
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    free = (closed == 0).astype(np.uint8)
    n, labels = cv2.connectedComponents(free, connectivity=4)
    reachable = np.unique(labels[0, :][labels[0, :] > 0])
    if reachable.size == 0:
        return None
    outside = np.isin(labels, reachable)
    mask = _clean(cv2.morphologyEx((~outside).astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k + 2, k + 2))).astype(bool))
    if not mask.any() or mask.mean() > 0.9:
        return None
    return Field("edge region", cv2.GaussianBlur(gray.astype(np.float32), (0, 0), 1.2), 0.0, mask, "any", float(np.percentile(np.abs(cv2.Laplacian(blur, cv2.CV_32F)), 99)), "edge")


def fields(bgr: np.ndarray, gray: np.ndarray) -> Iterator[Field]:
    yield grey_field(gray)
    bg = background_field(bgr)
    if bg is not None:
        yield bg
    ed = edge_field(gray)
    if ed is not None:
        yield ed


def _fit_line(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    a, b = np.polyfit(x.astype(float), y.astype(float), 1)
    return float(a), float(b)


def _ransac_line(x: np.ndarray, y: np.ndarray, tol: float, max_slope: float, min_gap: float, rng: np.random.Generator, iters: int = 400) -> tuple[float, float, np.ndarray] | None:
    """Most supported line with almost nothing below it (the surface is the lowest straight top edge)."""
    if x.size < 8:
        return None
    i, j = rng.integers(0, x.size, iters), rng.integers(0, x.size, iters)
    dx = x[j] - x[i].astype(float)
    ok = np.abs(dx) >= min_gap
    if not ok.any():
        return None
    a = (y[j] - y[i])[ok] / dx[ok]
    b = y[i][ok] - a * x[i][ok]
    ok2 = np.abs(a) <= max_slope
    if not ok2.any():
        return None
    a, b = a[ok2], b[ok2]
    r = y[None, :] - (a[:, None] * x[None, :] + b[:, None])
    score = (np.abs(r) <= tol).sum(axis=1) - 3 * (r > tol).sum(axis=1)
    k = int(np.argmax(score))
    best_a, best_b = float(a[k]), float(b[k])
    for _ in range(2):
        keep = np.abs(y - (best_a * x + best_b)) <= tol
        if keep.sum() < 6:
            return None
        best_a, best_b = _fit_line(x[keep], y[keep])
    return best_a, best_b, np.abs(y - (best_a * x + best_b)) <= tol


def surface_line(mask: np.ndarray, rng: np.random.Generator) -> Guess | None:
    """Specimen surface from the top foreground profile, re-fitted locally around the droplet."""
    h, w = mask.shape
    has = mask.any(axis=0)
    if has.sum() < 0.3 * w:
        return None
    x = np.flatnonzero(has).astype(float)
    y = mask.argmax(axis=0)[has].astype(float)
    tol = max(2.0, 0.005 * w)
    found = _ransac_line(x, y, tol, np.tan(np.radians(25)), 0.2 * w, rng)
    if found is None:
        return None
    a, b, inlier = found
    r = y - (a * x + b)
    rise = r < -max(3.0, 2 * tol)
    if not rise.any():
        return None
    # droplet span: longest run of columns rising above the line (small gaps allowed)
    cols = x[rise].astype(int)
    breaks = np.flatnonzero(np.diff(cols) > max(4, 0.01 * w))
    starts, ends = np.r_[0, breaks + 1], np.r_[breaks, cols.size - 1]
    best = int(np.argmax(cols[ends] - cols[starts]))
    xl, xr = int(cols[starts[best]]), int(cols[ends[best]])
    span = xr - xl
    if span < 8:
        return None
    margin = 0.6 * span
    left = inlier & (x < xl) & (x >= xl - margin)
    right = inlier & (x > xr) & (x <= xr + margin)
    n_side = max(5, 0.02 * w)
    two_sided = left.sum() >= n_side and right.sum() >= n_side
    if two_sided:
        a, b = _fit_line(x[left | right], y[left | right])
    rms = float(np.sqrt(np.mean((y[left | right] - (a * x[left | right] + b)) ** 2))) if (left | right).any() else tol
    conf = (0.95 if two_sided else 0.6) * float(np.clip(1.25 - rms / (3 * tol), 0.6, 1.0))
    return Guess("surface", a, b, conf, max(1.5, min(rms * 2, 2 * tol)), f"surface line, {'both sides' if two_sided else 'one side'} of the drop, RMS {rms:.2f} px")


def _largest(mask: np.ndarray) -> np.ndarray | None:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n < 2:
        return None
    return labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))


def mirror_axis(mask: np.ndarray) -> Guess | None:
    """Drop and its reflection on a polished surface: the contact line is the mirror-symmetry axis of the blob."""
    comp = _largest(mask)
    if comp is None:
        return None
    h, w = mask.shape
    f = min(1.0, 260 / max(h, w))
    small = cv2.resize(comp.astype(np.uint8), (max(8, int(w * f)), max(8, int(h * f))), interpolation=cv2.INTER_NEAREST)
    sy, sx = np.nonzero(small)
    if sy.size < 60:
        return None
    cx, cy = float(sx.mean()), float(sy.mean())
    best = None
    for ang in (0, -3, 3, -6, 6, -9, 9, -12, 12):
        M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
        rot = cv2.warpAffine(small, M, (small.shape[1], small.shape[0]), flags=cv2.INTER_NEAREST)
        rows = np.flatnonzero(rot.any(axis=1))
        if rows.size < 12:
            continue
        top, bottom = int(rows[0]), int(rows[-1])
        for y0 in range(top + 4, bottom - 1):
            k = min(y0 - top, rot.shape[0] - y0, bottom - y0 + 1)
            if k < max(4, 0.3 * (y0 - top)):
                continue
            up, dn = rot[y0 - k:y0], rot[y0:y0 + k][::-1]
            inter, union = int((up & dn).sum()), int((up | dn).sum())
            if union == 0:
                continue
            iou = inter / union
            if best is None or iou > best[0] + 1e-6:
                best = (iou, ang, y0, k)
    if best is None or best[0] < 0.62:
        return None
    iou, ang, y0, _ = best
    M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0)
    inv = cv2.invertAffineTransform(M)
    p1 = inv @ np.array([cx - 10, y0, 1.0])
    p2 = inv @ np.array([cx + 10, y0, 1.0])
    a = float((p2[1] - p1[1]) / (p2[0] - p1[0]))
    b = float(p1[1] / f - a * p1[0] / f)
    return Guess("mirror", a, b, float(np.clip(0.5 + (iou - 0.62) * 0.7, 0.5, 0.75)), 1.5, f"mirror axis between drop and reflection (overlap {iou:.2f})")


def flat_bottom(mask: np.ndarray, rng: np.random.Generator) -> Guess | None:
    """No visible substrate: the drop silhouette itself ends on a straight line."""
    comp = _largest(mask)
    if comp is None:
        return None
    h, w = mask.shape
    cols = np.flatnonzero(comp.any(axis=0))
    if cols.size < 12:
        return None
    last = h - 1 - comp[::-1, :].argmax(axis=0)
    x, y = cols.astype(float), last[cols].astype(float)
    tol = max(1.5, 0.004 * w)
    found = _ransac_line(x, -y, tol, np.tan(np.radians(25)), 0.15 * (cols[-1] - cols[0]), rng)
    if found is None:
        return None
    a, b, inlier = found
    a, b = -a, -b
    span = x[inlier].max() - x[inlier].min() if inlier.any() else 0
    height = np.ptp(np.flatnonzero(comp.any(axis=1)))
    if span < 0.25 * (cols[-1] - cols[0]) or span < 10 or height < 6:
        return None
    if y.max() - np.median(y[inlier]) > 0.08 * height + tol:
        return None
    return Guess("flat_bottom", a, b, 0.8, tol, f"straight lower edge of the drop ({span:.0f} px long)")


def hough_lines(gray: np.ndarray, limit: int = 3) -> list[Guess]:
    """Strongest long near-horizontal edges, as a last resort for the specimen surface."""
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (0, 0), 1.5)
    hi, _ = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(blur, max(10, 0.3 * hi), max(30, 0.7 * hi))
    segs = cv2.HoughLinesP(edges, 1, np.pi / 720, threshold=max(30, int(0.12 * w)), minLineLength=max(25, int(0.2 * w)), maxLineGap=max(6, int(0.03 * w)))
    if segs is None:
        return []
    lines: list[tuple[float, float, float]] = []
    for x1, y1, x2, y2 in segs.reshape(-1, 4):  # OpenCV 4 and 5 differ in the array shape
        if x2 == x1:
            continue
        a = (y2 - y1) / (x2 - x1)
        if abs(a) > np.tan(np.radians(25)):
            continue
        b = y1 - a * x1
        mid = a * w / 2 + b
        if not 0.12 * h <= mid <= 0.98 * h:
            continue
        length = float(np.hypot(x2 - x1, y2 - y1))
        for k, (la, lb, ll) in enumerate(lines):
            if abs(mid - (la * w / 2 + lb)) < 0.015 * h:
                if length > ll:
                    lines[k] = (float(a), float(b), length)
                break
        else:
            lines.append((float(a), float(b), length))
    lines.sort(key=lambda t: -t[2])
    return [Guess("hough", a, b, 0.42 + 0.15 * min(1.0, ln / w), 1.5, f"strongest straight edge ({ln:.0f} px)") for a, b, ln in lines[:limit]]


def gradient_edges(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    blur = cv2.GaussianBlur(gray, (0, 0), 1.5)
    gx, gy = cv2.Sobel(blur, cv2.CV_32F, 1, 0), cv2.Sobel(blur, cv2.CV_32F, 0, 1)
    mag = cv2.magnitude(gx, gy)
    hi = max(float(np.percentile(mag, 96)), 24.0)
    return cv2.Canny(blur, 0.45 * hi, hi, L2gradient=True) > 0, gx, gy, mag


def _walk(on: np.ndarray, gap: int, reach: int) -> tuple[int, int] | None:
    """Supported run through the top of a circle. Index 0 is the top, going clockwise. Returns (first, last), first <= 0 <= last."""
    n = on.size
    near = [k for d in range(reach + 1) for k in (d, -d) if on[k % n]]
    if not near:
        return None
    start = near[0]
    ends = [start, start]
    for side, sign in ((1, 1), (0, -1)):
        miss = 0
        for k in range(1, n):
            if on[(start + sign * k) % n]:
                ends[side], miss = start + sign * k, 0
            else:
                miss += 1
                if miss > gap:
                    break
    return ends[0], ends[1]


def outline_channels(bgr: np.ndarray) -> list[np.ndarray]:
    """Lightness with local contrast lifted, plus the two colour axes: lensed drops often separate from the scene by colour only."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lift = cv2.createCLAHE(3.0, (8, 8)).apply(lab[..., 0])
    return [cv2.GaussianBlur(c.astype(np.float32), (0, 0), 1.2) for c in (lift, lab[..., 1], lab[..., 2])]


def find_circles(gray: np.ndarray, rng: np.random.Generator, limit: int = 5) -> list[tuple[float, float, float]]:
    """Large circular arcs that pass over their own top. Edge normals of a circle meet at its centre, so pairs of edge
    points vote for a centre and radius; the busiest votes are then checked against edge points with a radial gradient."""
    h, w = gray.shape
    f = min(1.0, 640 / max(h, w))
    small = cv2.resize(gray, (max(8, round(w * f)), max(8, round(h * f))), interpolation=cv2.INTER_AREA) if f < 1 else gray
    edges, gx, gy, mag = gradient_edges(cv2.createCLAHE(3.0, (8, 8)).apply(small))
    ys, xs = np.nonzero(edges)
    if xs.size < 30:
        return []
    if xs.size > 8000:
        k = rng.choice(xs.size, 8000, replace=False)
        xs, ys = xs[k], ys[k]
    near = np.argsort((ys // 48) * 10000 + xs // 48)  # neighbours in this order are neighbours in the image
    xs, ys = xs[near], ys[near]
    X, Y = xs.astype(np.float32), ys.astype(np.float32)
    m = np.maximum(mag[ys, xs], 1e-3)
    nx, ny = gx[ys, xs] / m, gy[ys, xs] / m
    # half the pairs are local, so that a small drop among many texture edges still gets votes
    i = rng.integers(0, X.size, 80000)
    j = np.r_[rng.integers(0, X.size, 40000), np.minimum(i[40000:] + rng.integers(1, 150, 40000), X.size - 1)]
    det = nx[i] * ny[j] - ny[i] * nx[j]
    ok = np.abs(det) > 0.25
    i, j, det = i[ok], j[ok], det[ok]
    dx, dy = X[j] - X[i], Y[j] - Y[i]
    a, b = (dx * ny[j] - dy * nx[j]) / det, (dx * ny[i] - dy * nx[i]) / det
    r = (np.abs(a) + np.abs(b)) / 2
    sh, sw = small.shape
    cx, cy = X[i] + a * nx[i], Y[i] + a * ny[i]
    ok = (np.abs(np.abs(a) - np.abs(b)) < 0.05 * r) & (r >= max(10.0, 0.04 * min(sh, sw))) & (r <= 1.1 * max(sh, sw)) & (cx > -0.5 * sw) & (cx < 1.5 * sw) & (cy > -0.5 * sh) & (cy < 2 * sh)
    if ok.sum() < 5:
        return []
    cx, cy, r = cx[ok], cy[ok], r[ok]
    key = ((cx + sw) / 6).astype(np.int64) * 1_000_000 + ((cy + sh) / 6).astype(np.int64) * 1_000 + (r / 6).astype(np.int64)
    _, inverse, counts = np.unique(key, return_inverse=True, return_counts=True)
    top = np.argsort(-counts)[:120]
    cx, cy, r = (np.bincount(inverse, weights=v)[top] / counts[top] for v in (cx, cy, r))
    ddx, ddy = X[None, :] - cx[:, None], Y[None, :] - cy[:, None]
    dist = np.hypot(ddx, ddy)
    on = (np.abs(dist - r[:, None]) < np.maximum(1.2, 0.02 * r)[:, None]) & (np.abs(ddx * nx + ddy * ny) > 0.9 * dist)
    found: list[tuple[float, float, float, float]] = []
    for c in np.argsort(-on.sum(axis=1))[:40]:
        sel = on[c]
        if sel.sum() < 12:
            continue
        bins = np.zeros(72, bool)  # 5 degree bins, 0 = top of the circle, clockwise
        bins[(((np.degrees(np.arctan2(ddy[c, sel], ddx[c, sel])) + 90) % 360) // 5).astype(int)] = True
        run = _walk(bins, 3, 5)
        if run is None:
            continue
        span = (run[1] - run[0] + 1) * 5
        if span < MIN_ARC_DEG or bins[np.arange(run[0], run[1] + 1) % 72].mean() < 0.6:
            continue
        cand = (float(cx[c]) / f, float(cy[c]) / f, float(r[c]) / f, float(sel.sum()) / float(r[c]))  # edge points per radian: complete circles first, big or small
        if all(np.hypot(cand[0] - q[0], cand[1] - q[1]) > 0.2 * q[2] or abs(cand[2] - q[2]) > 0.2 * q[2] for q in found):
            found.append(cand)
    found.sort(key=lambda q: -q[3])
    return [q[:3] for q in found[:limit]]


def _polar_path(grad: np.ndarray) -> np.ndarray:
    """Smooth path through a rays-by-offsets edge map that collects the most edge strength (one column per ray)."""
    n, m = grad.shape
    steps = np.arange(-2, 3)
    pen = 0.12 * np.abs(steps)
    score = grad[0].copy()
    back = np.zeros((n, m), np.int8)
    idx = np.arange(m)
    for i in range(1, n):
        cand = np.lib.stride_tricks.sliding_window_view(np.pad(score, 2, constant_values=-np.inf), 5) - pen
        best = cand.argmax(axis=1)
        score = cand[idx, best] + grad[i]
        back[i] = steps[best]
    path = np.zeros(n, int)
    path[-1] = int(score.argmax())
    for i in range(n - 1, 0, -1):
        path[i - 1] = path[i] + back[i, path[i]]
    return path


def trace_arc(channels: list[np.ndarray], cx: float, cy: float, r: float) -> Arc | None:
    """Follow the real boundary near a circle and stop where it ends. The whole outline is solved at once as the smoothest
    strong path, so refraction rims inside a transparent drop and specks outside it cannot pull single rays off course.
    The circle is re-centred on each pass; the last pass lets the shape depart from a circle to follow flattened drops."""
    h, w = channels[0].shape
    if r > 1.5 * max(h, w):
        return None
    th = np.radians(np.arange(720) / 2 + 180)  # rays start at the bottom, so that the path is free where it matters
    sin, cos = np.sin(th)[:, None], np.cos(th)[:, None]
    ang = ((th + np.pi) % (2 * np.pi)) - np.pi  # 0 at the top
    rows = np.arange(720)
    model = np.full(720, float(r))
    for frac, floor in ((0.12, 8.0), (0.07, 5.0), (0.04, 4.0), (0.03, 3.0)):
        half = max(floor, frac * r)
        offs = np.arange(-half, half + 0.1, 0.5)
        rr = model[:, None] + offs[None, :]
        x, y = cx + rr * sin, cy - rr * cos
        inside = (x.min(axis=1) >= 2) & (x.max(axis=1) < w - 2) & (y.min(axis=1) >= 2) & (y.max(axis=1) < h - 2)
        if inside.sum() < 60:
            return None
        grad = np.sqrt(sum(np.gradient(map_coordinates(c, [y.ravel(), x.ravel()], order=1, mode="nearest").reshape(x.shape), axis=1) ** 2 for c in channels))
        grad[~inside] = 0
        unit = max(float(np.percentile(grad.max(axis=1)[inside], 75)), 1e-3)
        # slight outward preference: refraction puts bright false rims just inside the true outline of a transparent drop
        path = np.clip(_polar_path(np.minimum(grad / unit, 1.5) * (1 + 0.25 * offs / half)), 1, grad.shape[1] - 2)
        g0, g1, g2 = grad[rows, path - 1], grad[rows, path], grad[rows, path + 1]
        curve = g0 - 2 * g1 + g2
        found = model + offs[path] + 0.25 * np.clip((g0 - g2) / np.where(curve == 0, -1, curve), -2, 2)
        upper = inside & (np.abs(ang) < np.radians(70))
        if upper.sum() < 30:
            return None
        strong = inside & (g1 > max(0.8, 0.15 * float(np.median(g1[upper]))))
        keep = strong
        if keep.sum() < 40:
            return None
        if frac > 0.03:
            pts = np.column_stack([cx + found * sin[:, 0], cy - found * cos[:, 0]])
            for _ in range(3):
                c = fit_circle(pts[keep])
                res = np.abs(np.hypot(pts[:, 0] - c.uc, pts[:, 1] - c.vc) - c.r)
                keep = strong & (res <= max(1.5, 2.5 * 1.4826 * float(np.median(res[keep]))))
                if keep.sum() < 30:
                    return None
            cx, cy, r = c.uc, c.vc, c.r
            model = np.full(720, r)
        else:
            for _ in range(3):
                q = np.polyfit(ang[keep], found[keep], 4)
                res = np.abs(found - np.polyval(q, ang))
                keep = strong & (res <= max(1.5, 2.5 * 1.4826 * float(np.median(res[keep]))))
                if keep.sum() < 30:
                    return None
            model = np.polyval(q, ang)
    ok = strong & (np.abs(found - model) <= max(1.5, 0.012 * r))
    density = np.convolve(np.r_[ok[-12:], ok, ok[:12]].astype(float), np.ones(25) / 25, mode="same")[12:-12]
    # rays were numbered from the bottom: rotate so that index 0 is the top for the walk
    run = _walk(np.roll(ok & (density >= 0.5), -360), 70, 80)  # overlay text or a needle can hide a long stretch
    if run is None:
        return None
    span = (run[1] - run[0] + 1) / 2
    if span < MIN_ARC_DEG or ok[(np.arange(run[0], run[1] + 1) + 360) % 720].mean() < 0.5:
        return None
    xy = np.column_stack([cx + found * sin[:, 0], cy - found * cos[:, 0]])
    ends = xy[[(run[0] + 360) % 720, (run[1] + 360) % 720]]
    if ends[:, 0].min() < 0.015 * w or ends[:, 0].max() > 0.985 * w:
        return None  # the outline runs out of the frame: that end is the image border, not a contact point
    pts = xy[ok]
    c = fit_circle(xy[(np.abs(ang) < np.radians(span / 2)) & ok])
    arc = Arc(c.uc, c.vc, c.r, pts, ends, float(span), float(np.median(g1[ok])), top_fill=float(ok[np.abs(ang) < np.radians(60)].mean()))
    arc.step = step_line(channels, arc)
    return arc


def _reached(arc: Arc, a: float, b: float) -> bool:
    """Does the outline come down to this line on both sides? Otherwise the line is not where the drop stands."""
    th = np.radians(np.arange(720) / 2)
    y, x = arc.cy - arc.r * np.cos(th), arc.cx + arc.r * np.sin(th)
    px, py = arc.points[:, 0], arc.points[:, 1]
    band = 0.3 * arc.r
    for side in (-1, 1):
        rays = (side * (x - arc.cx) > 0) & (y < a * x + b) & (y > a * x + b - band)
        hits = (side * (px - arc.cx) > 0) & (py < a * px + b) & (py > a * px + b - band)
        if rays.sum() < 6 or hits.sum() < 0.15 * rays.sum():
            return False
    return True


def _step_peaks(lift: np.ndarray, xl: np.ndarray, xr: np.ndarray, ys: np.ndarray, cx: float, k: int) -> list[tuple[float, float, float]]:
    """Straight brightness steps seen at the same height in two side windows, as (slope, y at cx, strength), lowest first."""
    kernel = np.r_[np.ones(k), -np.ones(k)] / k

    def step(xs: np.ndarray, a: float) -> np.ndarray:
        yy = ys[:, None] + a * (xs[None, :] - cx)
        rows = map_coordinates(lift, [yy.ravel(), np.tile(xs, ys.size)], order=1, mode="nearest").reshape(yy.shape).mean(axis=1)
        out = np.convolve(rows, kernel, mode="same")  # positive: brighter below the line
        out[:k], out[-k:] = 0, 0
        return out

    tilts = np.arange(-15, 15.1, 1.5)
    slopes = np.tan(np.radians(tilts))
    table = np.zeros((tilts.size, ys.size))
    for i, a in enumerate(slopes):
        sl, sr = step(xl, float(a)), step(xr, float(a))
        table[i] = np.where(np.sign(sl) == np.sign(sr), np.minimum(np.abs(sl), np.abs(sr)), 0.0) * (1 - 0.02 * abs(tilts[i]))
    tilt_at, s = table.argmax(axis=0), table.max(axis=0)
    floor = max(6.0, 0.4 * float(s.max()), 2 * float(np.median(s)))
    peaks = [i for i in range(1, s.size - 1) if s[i] >= floor and s[i] == s[max(0, i - k):i + k + 1].max()]
    out = []
    xlm, xrm = float(xl.mean()), float(xr.mean())
    for i in sorted(peaks, reverse=True):
        a = float(slopes[tilt_at[i]])
        # the coarse slope is refined by locating the step in each window on its own
        dl, dr = (int(np.abs(step(xs, a)[max(0, i - 2 * k):i + 2 * k + 1]).argmax()) + max(0, i - 2 * k) - i for xs in (xl, xr))
        gap = xrm - xlm
        fine = a + float(ys[1] - ys[0]) * (dr - dl) / gap
        out.append((fine, float(ys[i]) + float(ys[1] - ys[0]) * (dl + (dr - dl) * (cx - xlm) / gap), float(s[i])))
    return out


def step_line(channels: list[np.ndarray], arc: Arc) -> Guess | None:
    """Specimen surface beside a traced drop: the lowest two-sided brightness step that the outline comes down to, since a
    background horizon can sit higher and the plate's lower edge lower. This needs no clean contact point, so it survives
    rough surfaces, shadows and a lower outline lost in the dark."""
    lift = channels[0]
    h, w = lift.shape
    cx, cy, r = arc.cx, arc.cy, arc.r
    ys = np.arange(max(1.0, cy - 0.97 * r), min(h - 1.0, cy + 1.08 * r), 1.0)
    xl, xr = cx - r * np.linspace(1.06, 1.75, 24), cx + r * np.linspace(1.06, 1.75, 24)
    xl, xr = xl[xl >= 2], xr[xr <= w - 3]
    if ys.size < 8 or xl.size < 6 or xr.size < 6:
        return None
    for a, y0, strength in _step_peaks(lift, xl, xr, ys, cx, max(3, int(0.05 * r))):
        b = y0 - a * cx
        if _reached(arc, a, b):
            return Guess("surface step", a, b, float(np.clip(0.7 + strength / 120, 0.7, 0.92)), 1.5, f"surface edge on both sides of the drop (step of {strength:.0f} grey levels)")
    return None


def global_lines(channels: list[np.ndarray], limit: int = 3) -> list[Guess]:
    """The specimen surface as a straight step across the whole image, found before looking for any drop. Averaging along
    the line makes this indifferent to grain, scratches and roughness on the plate, which defeat a pixel threshold."""
    lift = channels[0]
    h, w = lift.shape
    ys = np.arange(0.08 * h, h - 2.0, max(1.0, h / 600))
    xl, xr = np.linspace(0.02 * w, 0.3 * w, 40), np.linspace(0.7 * w, 0.98 * w, 40)
    peaks = sorted(_step_peaks(lift, xl, xr, ys, w / 2, max(3, int(0.012 * h))), key=lambda q: -q[2])[:limit]
    return [Guess("surface", a, y0 - a * w / 2, float(np.clip(0.75 + s / 150, 0.75, 0.95)), 2.0, f"straight surface edge across the image (step of {s:.0f} grey levels)") for a, y0, s in peaks]


def stands_out(gray: np.ndarray, arc: Arc) -> bool:
    """Contrast lifting finds faint outlines but also makes plain noise look like one, so a traced outline must show a
    real brightness step across it in the untouched image."""
    blur = cv2.GaussianBlur(gray, (0, 0), 2.0).astype(np.float32)
    rel = arc.points - [arc.cx, arc.cy]
    across = rel / np.maximum(np.linalg.norm(rel, axis=1, keepdims=True), 1e-6) * max(3.0, 0.03 * arc.r)
    inner, outer = arc.points - across, arc.points + across
    a = map_coordinates(blur, [inner[:, 1], inner[:, 0]], order=1, mode="nearest")
    b = map_coordinates(blur, [outer[:, 1], outer[:, 0]], order=1, mode="nearest")
    return float(np.median(np.abs(a - b))) >= 2.5


def arc_lines(arc: Arc, surfaces: list[Guess]) -> list[Guess]:
    """Baselines for a traced arc: the surface beside the drop, a straight edge agreeing with both arc ends, else the line through the ends."""
    pl, pr = arc.ends
    out: list[Guess] = [arc.step] if arc.step is not None else []
    band = max(4.0, 0.1 * arc.r)
    for g in surfaces:
        if max(abs(g.a * pl[0] + g.b - pl[1]), abs(g.a * pr[0] + g.b - pr[1])) <= band:
            out.append(Guess("surface edge + outline", g.a, g.b, 0.84, 1.5, "straight surface edge meeting both ends of the outline"))
    if arc.span_deg < 340 and pr[0] - pl[0] > 0.3 * arc.r:
        a = float((pr[1] - pl[1]) / (pr[0] - pl[0]))
        tilt = abs(np.degrees(np.arctan(a)))
        if tilt <= 20:
            out.append(Guess("outline ends", a, float(pl[1] - a * pl[0]), 0.8 - 0.012 * tilt, 1.5, f"line through both ends of the outline ({arc.span_deg:.0f} deg of arc)"))
        lower = pl if pl[1] > pr[1] else pr
        out.append(Guess("level through outline end", 0.0, float(lower[1]), 0.55, 1.5, "level line through the lower end of the outline"))
    return out


def continues_below(arc: Arc, a: float, b: float) -> float:
    """Share of the circle between a line and the surface beside the drop that still carries outline, 0..1. A true contact
    line ends the outline; a line drawn through the body of a drop leaves outline underneath it."""
    if arc.step is None:
        # without a known surface only a clean outline counts: patchy ones may be texture in the plate
        ends_below = (arc.ends[:, 1] - (a * arc.ends[:, 0] + b)).min() > 0.15 * arc.r
        return 1.0 if arc.top_fill >= 0.8 and ends_below else 0.0
    th = np.radians(np.arange(720) / 2)
    y, x = arc.cy - arc.r * np.cos(th), arc.cx + arc.r * np.sin(th)
    px, py = arc.points[:, 0], arc.points[:, 1]
    rays = (y > a * x + b + 3) & (y < arc.step.a * x + arc.step.b - 3)
    hits = (py > a * px + b + 3) & (py < arc.step.a * px + arc.step.b - 3)
    if rays.sum() < 30:
        return 0.0
    return float(min(1.0, hits.sum() / rays.sum()))


def needle_end(comp: np.ndarray) -> int | None:
    """Row where a dispensing needle joins the drop: a stem much narrower than the drop, running down from the top."""
    rows = comp.sum(axis=1)
    ys = np.flatnonzero(rows)
    top, widest = int(ys[0]), int(rows.argmax())
    narrow = rows[top:widest] < 0.35 * rows[widest]
    if narrow.size == 0:
        return None
    n = narrow.size if narrow.all() else int(narrow.argmin())
    return top + n if n >= 0.12 * (ys[-1] - top) else None


def baselines(mask: np.ndarray, gray: np.ndarray, rng: np.random.Generator) -> list[Guess]:
    out: list[Guess] = []
    for g in (surface_line(mask, rng), mirror_axis(mask), flat_bottom(mask, rng)):
        if g is not None:
            out.append(g)
    return sorted(out, key=lambda g: -g.confidence)
