"""Reproducibly derive the showcase analysis image from the downloaded source frame.

Source: "Contact angle measurement with Attension Theta" by Jyrkorpela, Wikimedia Commons, CC BY-SA 4.0
https://commons.wikimedia.org/wiki/File:Contact_angle_measurement_with_Attension_Theta.png

Steps (documented in data/showcase/showcase.json):
1. crop the camera viewport (x 95-610, y 28-378 of the 961x542 screenshot);
2. remove the third-party orange overlay (angle labels, baseline line, volume text) by OpenCV
   Telea inpainting of pixels with R - B > 60 and R > 90, dilated 5x5. Nothing else is altered.

Usage: backend\\.venv\\Scripts\\python scripts\\prepare_showcase_image.py
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

SHOWCASE = Path(__file__).resolve().parents[1] / "data" / "showcase"
CROP = (95, 28, 610, 378)  # x0, y0, x1, y1


def main() -> None:
    src = cv2.imread(str(SHOWCASE / "source_attension_theta_frame.png"))
    if src is None:
        raise SystemExit("data/showcase/source_attension_theta_frame.png missing")
    x0, y0, x1, y1 = CROP
    crop = src[y0:y1, x0:x1]
    b, _, r = (crop[..., i].astype(int) for i in range(3))
    mask = cv2.dilate(((r - b > 60) & (r > 90)).astype(np.uint8) * 255, np.ones((5, 5), np.uint8))
    clean = cv2.inpaint(crop, mask, 4, cv2.INPAINT_TELEA)
    cv2.imwrite(str(SHOWCASE / "droplet_for_analysis.png"), clean)
    print(f"wrote data/showcase/droplet_for_analysis.png ({clean.shape[1]}x{clean.shape[0]}), inpainted {int((mask > 0).sum())} px")


if __name__ == "__main__":
    main()
