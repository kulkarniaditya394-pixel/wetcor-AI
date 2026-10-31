"""Measure the contact-angle detector on rendered imperfect images with known true angles.

Every scene is a physically shaped droplet (spherical cap, or Young-Laplace with gravity for large drops) rendered with one
imperfection. Because the true angle is known exactly, the error of the detector can be measured instead of assumed.
Run: backend\\.venv\\Scripts\\python scripts\\evaluate_contact_angle.py [--quick] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.integrate import solve_ivp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.wettability.detection import analyze  # noqa: E402

W, H = 800, 600


def profile(theta_deg: float, r_px: float, bond: float = 0.0) -> np.ndarray:
    """Half outline (x from the axis, height above the surface), apex first, ending at the contact point."""
    theta = np.radians(theta_deg)
    if bond <= 0:
        phi = np.linspace(0, theta, 300)
        x, y = r_px * np.sin(phi), r_px * (np.cos(phi) - np.cos(theta))
        return np.column_stack([x, y])
    # Young-Laplace in arc length, lengths in units of the apex radius, bond = rho g b^2 / gamma
    def rhs(_, q):
        x, z, phi = q
        curv = 2 + bond * z - (np.sin(phi) / x if x > 1e-9 else 1.0)
        return [np.cos(phi), np.sin(phi), curv]

    stop = lambda _, q: q[2] - theta  # noqa: E731
    stop.terminal = True
    sol = solve_ivp(rhs, (0, 12), [0, 0, 0], max_step=0.01, events=stop, rtol=1e-8, atol=1e-9)
    x, z = sol.y[0], sol.y[1]
    span = x.max()
    k = r_px / span
    return np.column_stack([x * k, (z[-1] - z) * k])


def scene(theta: float, *, r: float = 150, tilt: float = 0, bg: str = "flat", surface: str = "dark", drop: str = "dark", bond: float = 0.0,
          reflect: bool = False, needle: bool = False, text: bool = False, blur: float = 0.8, noise: float = 2.0, jpeg: int | None = None,
          scale: float = 1.0, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    S = 3  # supersampled, so that edges are antialiased as a lens would make them
    w, h = W * S, H * S
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xn, yn = xx / w * 2 - 1, yy / h * 2 - 1
    if bg == "flat":
        img = np.full((h, w, 3), 225, np.float32)
    elif bg == "vignette":
        img = (235 - 170 * np.clip(xn**2 + yn**2 - 0.25, 0, 1))[..., None].repeat(3, 2)
    elif bg == "gradient":
        img = (120 + 90 * xn + 40 * yn)[..., None].repeat(3, 2)
    elif bg == "dark":
        img = np.full((h, w, 3), 28, np.float32)
    elif bg == "colour":
        img = np.stack([150 - 40 * yn, 170 + 30 * xn, 90 + 30 * yn], axis=2)  # olive photo background
    elif bg == "clutter":
        noise_img = cv2.GaussianBlur(rng.normal(0, 1, (h // 12, w // 12)).astype(np.float32), (0, 0), 3)
        noise_img = cv2.resize(noise_img / noise_img.std(), (w, h), interpolation=cv2.INTER_CUBIC)
        img = (140 + 38 * noise_img)[..., None].repeat(3, 2)
    else:
        raise ValueError(bg)
    prof = profile(theta, r * S if bond == 0 else r * S, bond)
    half = prof[-1, 0]
    cx, base = w * 0.5, h * 0.68
    outline = np.vstack([np.column_stack([cx - prof[::-1, 0], base - prof[::-1, 1]]), np.column_stack([cx + prof[:, 0], base - prof[:, 1]])])
    tilt_r = np.radians(tilt)
    rot = np.array([[np.cos(tilt_r), -np.sin(tilt_r)], [np.sin(tilt_r), np.cos(tilt_r)]])
    tilted = (outline - [cx, base]) @ rot.T + [cx, base]
    drop_mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(drop_mask, [tilted.astype(np.int32)], 255)
    dirn = rot @ np.array([1.0, 0.0])
    normal = rot @ np.array([0.0, 1.0])
    depth = (xx - cx) * normal[0] + (yy - base) * normal[1]
    below = depth > 0
    if surface == "dark":
        sub = np.full((h, w, 3), 45, np.float32)
    elif surface == "steel":
        grain = cv2.resize(cv2.GaussianBlur(rng.normal(0, 1, (h // 3, w // 3)).astype(np.float32), (0, 0), sigmaX=6, sigmaY=0.6), (w, h))
        sub = (150 + 20 * (grain / grain.std()))[..., None].repeat(3, 2)
    elif surface == "rough":
        bumps = cv2.GaussianBlur(rng.normal(0, 1, (h // 3, w // 3)).astype(np.float32), (0, 0), 2)
        sub = (85 + 20 * cv2.resize(bumps / bumps.std(), (w, h)))[..., None].repeat(3, 2)
        along = (xx - cx) * dirn[0] + (yy - base) * dirn[1]
        rough = np.interp(along.ravel(), np.linspace(-w, w, 500), cv2.GaussianBlur(rng.normal(0, 1, (500, 1)).astype(np.float32), (0, 0), 1.5).ravel() * 9 * S).reshape(along.shape)
        below = depth > rough * (np.abs(along) > half * 1.02)
    else:
        raise ValueError(surface)
    if reflect:
        mirror = ((xx - cx - 2 * depth * normal[0]).astype(np.float32), (yy - base - 2 * depth * normal[1]).astype(np.float32))
    img = np.where(below[..., None], sub, img)
    if drop == "dark":
        body = np.full((h, w, 3), 30, np.float32)
    elif drop == "lens":
        # transparent drop: inverted scene, dark rim, bright inner rim and a highlight
        inv = img[::-1, ::-1] * 0.8
        d = cv2.distanceTransform(drop_mask, cv2.DIST_L2, 5)
        rim = np.exp(-d / (0.1 * r * S))
        inner = np.exp(-(((d - 0.06 * r * S) / (0.02 * r * S)) ** 2))
        body = inv * (1 - 0.85 * rim)[..., None] + 90 * inner[..., None]
        hl = np.exp(-(((xx - cx + 0.3 * half) / (0.1 * r * S)) ** 2 + ((yy - base + 1.1 * prof[0, 1] * 0.8) / (0.07 * r * S)) ** 2))
        body = body + 150 * hl[..., None]
    elif drop == "faint":
        body = img - 16
    else:
        raise ValueError(drop)
    if reflect:
        ref = cv2.remap(drop_mask, mirror[0], mirror[1], cv2.INTER_LINEAR)
        img = np.where((ref > 127)[..., None] & below[..., None], img * 0.35, img)
    img = np.where((drop_mask > 127)[..., None], body, img)
    if needle:
        nw = 0.13 * half
        top = base - prof[0, 1]
        img[: int(top + 0.03 * r * S), int(cx - nw): int(cx + nw)] = 25
    img = np.clip(img, 0, 255).astype(np.uint8)
    img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
    if text:
        cv2.putText(img, "CA 12.3  sample-07", (24, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(img, "2026-10-31 14:22", (W - 260, H - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
    if blur:
        img = cv2.GaussianBlur(img, (0, 0), blur)
    if noise:
        img = np.clip(img + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return img


def encode(img: np.ndarray, jpeg: int | None) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg]) if jpeg else cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


# name: scene arguments. Angles are chosen per scene where a feature only exists for some angles.
SCENARIOS: dict[str, dict] = {
    "clean back-lit": {},
    "tilted +8 deg": {"tilt": 8},
    "tilted -15 deg": {"tilt": -15},
    "vignette": {"bg": "vignette"},
    "gradient background": {"bg": "gradient"},
    "colour background": {"bg": "colour"},
    "dark background, bright drop": {"bg": "dark", "drop": "lens", "surface": "steel"},
    "cluttered background": {"bg": "clutter"},
    "brushed steel plate": {"surface": "steel"},
    "rough surface": {"surface": "rough"},
    "mirror reflection": {"surface": "steel", "reflect": True},
    "transparent lens drop": {"drop": "lens", "bg": "colour", "surface": "rough"},
    "dispensing needle": {"needle": True},
    "overlay text": {"text": True},
    "heavy blur": {"blur": 3.0},
    "heavy noise": {"noise": 18},
    "strong JPEG": {"jpeg": 18},
    "low resolution 200 px": {"scale": 0.25},
    "faint drop": {"drop": "faint", "bg": "gradient"},
    "gravity-flattened": {"bond": 0.6, "r": 230},
    "everything at once": {"tilt": 6, "bg": "vignette", "surface": "steel", "needle": True, "text": True, "blur": 1.5, "noise": 8, "jpeg": 45},
}
ANGLES = [35, 60, 85, 110, 135, 150]


def real_set() -> None:
    """Compare with the angles that the authors of openly licensed images published (see data/validation/README.md)."""
    folder = ROOT / "data" / "validation"
    labels = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    errs = []
    for item in labels:
        r = analyze((folder / item["file"]).read_bytes())
        d = r["detection"] or {}
        got = r["mean_deg"]
        if got is not None:
            errs.append(abs(got - item["label_deg"]))
        print(f"{item['file']:28s} published {item['label_deg']:7.2f}  measured {got}  {r['status']}  {d.get('strategy')}  {d.get('evidence')}  {(r['errors'] or [''])[0][:50]}")
    print(f"measured {len(errs)}/{len(labels)}, median difference {statistics.median(errs):.2f} deg, max {max(errs):.2f} deg")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--real", action="store_true", help="compare with the published angles in data/validation")
    ap.add_argument("--json")
    ap.add_argument("--only")
    ap.add_argument("--dump", help="write the rendered scenes to this folder")
    args = ap.parse_args()
    if args.real:
        real_set()
        return
    angles = [60, 110] if args.quick else ANGLES
    rows = []
    t0 = time.time()
    for name, kw in SCENARIOS.items():
        if args.only and args.only not in name:
            continue
        kw = dict(kw)
        jpeg = kw.pop("jpeg", None)
        errs, states, wrong = [], {"ok": 0, "needs_correction": 0, "failed": 0}, 0
        for i, theta in enumerate(angles):
            img = scene(theta, seed=i, **kw)
            if args.dump:
                Path(args.dump).mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(Path(args.dump) / f"{name.replace(' ', '_')}_{theta}.png"), img)
            r = analyze(encode(img, jpeg))
            states[r["status"]] += 1
            if r["mean_deg"] is None:
                continue
            err = abs(r["mean_deg"] - theta)
            errs.append(err)
            if r["status"] == "ok" and err > 8:
                wrong += 1
        rows.append({"scenario": name, "images": len(angles), "measured": len(errs), "ok": states["ok"], "flagged": states["needs_correction"], "refused": states["failed"],
                     "median_error_deg": round(statistics.median(errs), 2) if errs else None, "max_error_deg": round(max(errs), 2) if errs else None, "silently_wrong": wrong})
        print(f"{name:30s} measured {len(errs)}/{len(angles)}  ok {states['ok']}  flagged {states['needs_correction']}  refused {states['failed']}  "
              f"median {rows[-1]['median_error_deg']}  max {rows[-1]['max_error_deg']}  wrong-unflagged {wrong}", flush=True)
    all_err = sum(r["measured"] for r in rows), sum(r["images"] for r in rows), sum(r["silently_wrong"] for r in rows)
    print(f"\nmeasured {all_err[0]}/{all_err[1]} images, unflagged errors above 8 deg: {all_err[2]}, {time.time() - t0:.0f} s")
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
