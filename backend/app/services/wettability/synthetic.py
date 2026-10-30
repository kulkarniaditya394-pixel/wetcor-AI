"""SYNTHETIC sessile-drop images with contact angles known by construction (tests and demo only).

Each side of the profile is an arc of a circle whose centre lies on the drop axis; both arcs share
the apex (horizontal tangent), so left and right contact angles can differ while the profile stays
smooth. Rendered with 4x supersampling and area averaging, optionally tilted, noisy or low contrast.
"""
from __future__ import annotations

import cv2
import numpy as np


def synthetic_drop(
    theta_left: float,
    theta_right: float | None = None,
    *,
    size: tuple[int, int] = (640, 480),
    radius_px: float = 140.0,
    centre_x: float | None = None,
    baseline_y: float = 340.0,
    tilt_deg: float = 0.0,
    background: float = 215.0,
    foreground: float = 35.0,
    substrate: bool = True,
    noise_sigma: float = 1.5,
    seed: int = 0,
    ss: int = 4,
) -> tuple[np.ndarray, dict]:
    """Returns (grey uint8 image, ground truth dict with angles and contact points in image coords)."""
    theta_right = theta_left if theta_right is None else theta_right
    w, h = size
    cx = w / 2 if centre_x is None else centre_x
    tl, tr = np.radians(theta_left), np.radians(theta_right)
    r_l = radius_px
    apex = r_l * (1 - np.cos(tl))
    r_r = apex / (1 - np.cos(tr))
    a = np.radians(tilt_deg)
    d, n = np.array([np.cos(a), np.sin(a)]), np.array([np.sin(a), -np.cos(a)])

    coords = (np.arange(w * ss) + 0.5) / ss - 0.5
    rows = (np.arange(h * ss) + 0.5) / ss - 0.5
    xx, yy = np.meshgrid(coords, rows)
    u = (xx - cx) * d[0] + (yy - baseline_y) * d[1]
    v = (xx - cx) * n[0] + (yy - baseline_y) * n[1]
    left = (u <= 0) & (u**2 + (v - (apex - r_l)) ** 2 <= r_l**2)
    right = (u > 0) & (u**2 + (v - (apex - r_r)) ** 2 <= r_r**2)
    dark = (v >= 0) & (left | right)
    if substrate:
        dark |= v < 0
    hi = np.where(dark, foreground, background)
    img = hi.reshape(h, ss, w, ss).mean(axis=(1, 3))
    if noise_sigma:
        img = img + np.random.default_rng(seed).normal(0, noise_sigma, img.shape)
    img = np.clip(np.round(img), 0, 255).astype(np.uint8)

    def to_xy(uu: float, vv: float) -> list[float]:
        p = np.array([cx, baseline_y]) + uu * d + vv * n
        return [float(p[0]), float(p[1])]

    truth = {
        "theta_left": float(theta_left), "theta_right": float(theta_right),
        "contact_left": to_xy(-r_l * np.sin(tl), 0.0), "contact_right": to_xy(r_r * np.sin(tr), 0.0),
        "apex": to_xy(0.0, apex), "baseline": [to_xy(-cx, 0.0), to_xy(w - cx, 0.0)], "tilt_deg": float(tilt_deg),
    }
    return img, truth


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()
