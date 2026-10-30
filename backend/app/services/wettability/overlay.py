"""Annotated overlay rendering. Draws on a copy; the original image is never modified."""
from __future__ import annotations

import cv2
import numpy as np

from app.services.wettability.detection import decode_image

# BGR
CYAN, GREEN, AMBER, MAGENTA, WHITE = (220, 200, 40), (90, 220, 90), (40, 180, 255), (200, 90, 220), (245, 245, 245)


def _pt(p) -> tuple[int, int]:
    return int(round(p[0])), int(round(p[1]))


def render_overlay(data: bytes, result: dict) -> bytes:
    bgr, _ = decode_image(data)
    img = bgr.copy()
    h, w = img.shape[:2]
    t = max(1, round(min(h, w) / 400))
    geo = result.get("geometry", {})
    if roi := geo.get("roi"):
        x, y, rw, rh = roi
        if (rw, rh) != (w, h):
            cv2.rectangle(img, (x, y), (x + rw - 1, y + rh - 1), WHITE, 1, cv2.LINE_AA)
    if contour := geo.get("contour"):
        cv2.polylines(img, [np.array(contour, dtype=np.int32).reshape(-1, 1, 2)], False, GREEN, t, cv2.LINE_AA)
    if circle := geo.get("circle"):
        cv2.circle(img, _pt(circle["centre"]), int(round(circle["radius"])), MAGENTA, 1, cv2.LINE_AA)
    if base := geo.get("baseline"):
        cv2.line(img, _pt(base[0]), _pt(base[1]), CYAN, t, cv2.LINE_AA)
    for side in ("left", "right"):
        if seg := geo.get(f"tangent_{side}"):
            cv2.line(img, _pt(seg[0]), _pt(seg[1]), AMBER, t, cv2.LINE_AA)
        if cp := geo.get(f"contact_{side}"):
            cv2.circle(img, _pt(cp), 3 * t + 2, AMBER, t, cv2.LINE_AA)
    scale = max(0.5, min(h, w) / 900)
    lines = []
    if result.get("mean_deg") is not None:
        lines.append(f"L {result['left_deg']:.1f}  R {result['right_deg']:.1f}  mean {result['mean_deg']:.1f} deg")
        lines.append(f"{result.get('method')}  [{result.get('algorithm_version')}]")
    else:
        lines.append(f"Analysis {result.get('status')}")
    for i, text in enumerate(lines):
        org = (10, int(30 * scale * (i + 1)))
        cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.8 * scale, (0, 0, 0), 4 * t, cv2.LINE_AA)
        cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, 0.8 * scale, WHITE, t, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("Could not encode overlay")
    return buf.tobytes()
