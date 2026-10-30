"""Pure geometry for sessile-drop contact angles.

Coordinates: image pixels, x to the right, y DOWN. All angle work happens in a baseline frame
(u along the baseline, left to right; v perpendicular to it, positive towards the droplet, i.e. "up"
in the image), so a tilted specimen baseline is handled exactly.

Contact angle convention: the angle inside the liquid between the baseline (pointing into the drop)
and the tangent to the liquid-vapour boundary at the contact point. 0 deg < theta < 180 deg.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares


class GeometryError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    origin: np.ndarray
    d: np.ndarray  # unit vector along baseline (left -> right)
    n: np.ndarray  # unit normal pointing up in the image (towards the drop)

    def to_uv(self, pts: np.ndarray) -> np.ndarray:
        rel = np.atleast_2d(np.asarray(pts, dtype=float)) - self.origin
        return np.column_stack([rel @ self.d, rel @ self.n])

    def to_xy(self, uv: np.ndarray) -> np.ndarray:
        uv = np.atleast_2d(np.asarray(uv, dtype=float))
        return self.origin + np.outer(uv[:, 0], self.d) + np.outer(uv[:, 1], self.n)

    @property
    def tilt_deg(self) -> float:
        # Positive = baseline descends to the right in the image.
        return float(np.degrees(np.arctan2(self.d[1], self.d[0])))


def make_frame(p1, p2) -> Frame:
    p1, p2 = np.asarray(p1, dtype=float), np.asarray(p2, dtype=float)
    if p2[0] < p1[0]:
        p1, p2 = p2, p1
    length = float(np.hypot(*(p2 - p1)))
    if length < 5:
        raise GeometryError("Baseline points are too close together (need at least 5 px apart).")
    d = (p2 - p1) / length
    if abs(d[1]) > np.sin(np.radians(45)):
        raise GeometryError("Baseline is tilted more than 45 deg; rotate the camera or the image.")
    return Frame(origin=p1, d=d, n=np.array([d[1], -d[0]]))


def tangent_angle_deg(t_uv: np.ndarray, side: str) -> float:
    """Angle between the inward baseline direction and an upward tangent vector t=(tu, tv)."""
    tu, tv = float(t_uv[0]), float(t_uv[1])
    if tv <= 0:
        raise GeometryError("Tangent does not point above the baseline.")
    sign = 1.0 if side == "left" else -1.0
    return float(np.degrees(np.arctan2(tv, sign * tu)))


def manual_tangent_angle(frame: Frame, contact_xy, tangent_xy, side: str) -> float:
    """Angle from a user-placed contact point and a second point on the tangent line."""
    c, t = frame.to_uv(contact_xy)[0], frame.to_uv(tangent_xy)[0]
    return tangent_angle_deg(t - c, side)


@dataclass
class CircleFit:
    uc: float
    vc: float
    r: float
    rms: float

    @property
    def rel_rms(self) -> float:
        return self.rms / self.r

    def intersects_baseline(self) -> bool:
        return self.r > abs(self.vc)

    def contact_u(self) -> tuple[float, float]:
        half = float(np.sqrt(max(self.r**2 - self.vc**2, 0.0)))
        return self.uc - half, self.uc + half

    def angle_deg(self) -> float:
        # Spherical cap: cos(theta) = -vc / R (vc = centre height above baseline).
        return float(np.degrees(np.arccos(np.clip(-self.vc / self.r, -1.0, 1.0))))


def fit_circle(uv: np.ndarray) -> CircleFit:
    """Algebraic (Kasa) initial estimate refined by geometric least squares."""
    uv = np.asarray(uv, dtype=float)
    if len(uv) < 5:
        raise GeometryError("Too few boundary points for a circle fit.")
    u, v = uv[:, 0], uv[:, 1]
    a = np.column_stack([2 * u, 2 * v, np.ones_like(u)])
    sol, *_ = np.linalg.lstsq(a, u**2 + v**2, rcond=None)
    uc, vc = sol[0], sol[1]
    r0 = np.sqrt(max(sol[2] + uc**2 + vc**2, 1e-9))
    res = least_squares(lambda p: np.hypot(u - p[0], v - p[1]) - p[2], [uc, vc, r0], method="lm")
    uc, vc, r = res.x
    return CircleFit(float(uc), float(vc), float(abs(r)), float(np.sqrt(np.mean(res.fun**2))))


@dataclass
class SideFit:
    side: str
    angle_deg: float
    contact_uv: tuple[float, float]
    tangent_uv: tuple[float, float]  # unit tangent pointing up from the contact point
    rms_px: float
    n_points: int
    parameterisation: str  # "u(v)" or "v(u)"


def fit_side_tangent(points_uv: np.ndarray, contact_u_est: float, side: str, degree: int = 2) -> SideFit:
    """Local polynomial fit of one side of the profile, extrapolated to the baseline (v = 0).

    The points are rotated into their own principal-axis frame (s along the local profile direction,
    t across it) and t = q(s) is fitted there, so the fit is well conditioned for any contact angle.
    The fitted curve is intersected with the baseline and differentiated at that point.
    """
    pts = np.asarray(points_uv, dtype=float)
    if len(pts) < degree + 3:
        raise GeometryError(f"Too few points for the {side} tangent fit.")
    centre = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - centre, full_matrices=False)
    e1, e2 = vt[0], np.array([-vt[0][1], vt[0][0]])
    s, t = (pts - centre) @ e1, (pts - centre) @ e2
    q = np.polyfit(s, t, degree)
    rms = float(np.sqrt(np.mean((np.polyval(q, s) - t) ** 2)))
    # v(s) = centre_v + s*e1_v + q(s)*e2_v ; solve v(s) = 0
    v_poly = q * e2[1]
    v_poly[-1] += centre[1]
    v_poly[-2] += e1[1]
    roots = np.roots(v_poly)
    real = roots[np.abs(roots.imag) < 1e-6].real
    if not real.size:
        raise GeometryError(f"{side} profile fit does not reach the baseline.")
    s_est = (np.array([contact_u_est, 0.0]) - centre) @ e1
    s0 = float(real[np.argmin(np.abs(real - s_est))])
    contact = centre + s0 * e1 + np.polyval(q, s0) * e2
    tan = e1 + np.polyval(np.polyder(q), s0) * e2
    tan = tan if tan[1] > 0 else -tan
    if tan[1] <= 1e-9:
        raise GeometryError(f"{side} profile does not rise from the baseline.")
    tan = tan / np.hypot(*tan)
    return SideFit(side, tangent_angle_deg(tan, side), (float(contact[0]), 0.0), (float(tan[0]), float(tan[1])), rms, len(pts), "rotated-frame polynomial")


def classify(mean_deg: float | None, left_deg: float | None = None, right_deg: float | None = None,
             tolerance_deg: float = 2.0) -> dict | None:
    """Water-contact-angle wettability class. Uses the value at display precision (0.1 deg)."""
    if mean_deg is None:
        return None
    shown = round(mean_deg, 1)
    if shown < 90:
        label, text = "hydrophilic", "Hydrophilic (θ < 90°)"
    elif shown > 90:
        label, text = "hydrophobic", "Hydrophobic (θ > 90°)"
    else:
        label, text = "boundary", "At hydrophilic/hydrophobic boundary"
    reasons = []
    if abs(shown - 90) <= tolerance_deg:
        reasons.append(f"Mean is within the configured display tolerance of +/-{tolerance_deg:g} deg of 90 deg (software setting, not a physical uncertainty).")
    if left_deg is not None and right_deg is not None and min(left_deg, right_deg) < 90 < max(left_deg, right_deg):
        reasons.append("Left and right angles fall on opposite sides of 90 deg.")
    return {
        "label": label,
        "text": text,
        "uncertain": bool(reasons) or label == "boundary",
        "reasons": reasons,
        "recommend_repeat": bool(reasons) or label == "boundary",
    }
