# Contact-angle detector: measured performance

Algorithm `ca-2.0.0`. Every number here was measured by `scripts/evaluate_contact_angle.py` and can be reproduced with it.
The detector is a geometric algorithm developed on these images. It is **not** a trained neural network, and no model was
trained. Because the same images guided its development, these figures are likely to be somewhat better than on images it
has never seen. Real accuracy on this project's rig must still be established by a repeat study
(HARDWARE_VALIDATION.md).

## 1. Rendered imperfect images with a known true angle
Run: `backend\.venv\Scripts\python scripts\evaluate_contact_angle.py`

Each scene is a physically shaped drop (spherical cap, or Young-Laplace with gravity) rendered with one imperfection at 35,
60, 85, 110, 135 and 150 deg, so the true angle is exact. "Unflagged wrong" counts results reported as `ok` that are more
than 8 deg off.

| Scene | Measured | Median error (deg) | Worst error (deg) | Unflagged wrong |
|---|---|---|---|---|
| clean back-lit | 6/6 | 0.22 | 0.36 | 0 |
| tilted +8 deg | 6/6 | 0.12 | 0.68 | 0 |
| tilted -15 deg | 6/6 | 0.09 | 0.42 | 0 |
| vignette | 6/6 | 0.58 | 0.73 | 0 |
| gradient background | 6/6 | 0.28 | 0.47 | 0 |
| colour background | 6/6 | 0.25 | 0.38 | 0 |
| dark background, bright drop | 6/6 | 4.3 | 38.72 | 1 |
| cluttered background | 6/6 | 1.18 | 78.97 | 1 |
| brushed steel plate | 6/6 | 0.88 | 1.5 | 0 |
| rough surface | 6/6 | 0.79 | 3.93 | 0 |
| mirror reflection | 6/6 | 0.88 | 1.5 | 0 |
| transparent lens drop | 5/6 | 0.65 | 61.88 | 2 |
| dispensing needle | 6/6 | 0.21 | 0.36 | 0 |
| overlay text | 6/6 | 0.22 | 0.36 | 0 |
| heavy blur | 6/6 | 1.34 | 3.28 | 0 |
| heavy noise | 6/6 | 0.39 | 0.49 | 0 |
| strong JPEG | 6/6 | 0.36 | 1.88 | 0 |
| low resolution 200 px | 6/6 | 0.39 | 0.62 | 0 |
| faint drop | 5/6 | 0.19 | 0.38 | 0 |
| gravity-flattened | 6/6 | 0.84 | 21.39 | 1 |
| everything at once | 5/6 | 3.89 | 38.3 | 2 |

Total: 123/126 measured, 3 refused, 7 unflagged wrong (5.6 %).

The weakest scenes are transparent or bright drops at low angles, cluttered backgrounds and the combined worst case. Note the
worst-error column: a wrong baseline produces a large error, not a small one, which is why the overlay must always be
checked. Plate texture in these scenes is realistic grain (about 20 grey levels), not full black-and-white noise.

## 2. Published photographs
Run: `backend\.venv\Scripts\python scripts\evaluate_contact_angle.py --real`

Images and attribution are in `data/validation/`. The labels are the authors' readings, so this is a comparison and not
ground truth.

| Image | Published (deg) | Measured (deg) | Evidence |
|---|---|---|---|
| Transparent drop on rough sand, photo | 129.23 | 130.04 | medium |
| Transparent drop on rough sand, photo | 145.22 | 156.35 | medium |
| Goniometer frame with reflection, cropped | 114.62 | 118.6 | high |
| 18 tiny panels (about 165 px wide) from one table | 16 to 55 | median difference 5.8, worst 74.3, 1 refused | mixed |

The tiny panels are the known weak case: each is a drop plus its reflection, with a tangent line and a label printed on the
image, and the surface is a thin dark line instead of a brightness step. Crop tighter or place the baseline by hand on
images like these.

Mirror reflections with no visible surface step, very dark images and images holding several drops are also weak. Multi-panel
figures are not supported: crop one drop with the ROI. Round objects that are not drops can be measured by mistake, usually
with `medium` or `low` evidence, so a side-on drop image is the user's responsibility.

## 3. Hosted site versus local app
The hosted site runs the same Python code on a different OpenCV build (4.11 in Pyodide, 5.0 on the server), and the edge
sets differ slightly. Clean images agree. On the hardest transparent-drop photo the two gave up to about 7 deg apart, so
that is a fair statement of the method's sensitivity on such images.
