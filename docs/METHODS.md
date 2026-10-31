# Scientific methods and assumptions

This document describes exactly what WETCOR AI computes. Version identifiers stored with every result:
contact-angle algorithm `ca-2.0.0`, electrochemistry methods `ec-1.0.0`, Arduino rig analysis `rig-1.0.0`.

All limits referred to below are **software quality-control settings** (Settings page, `app_settings` table).
Each saved result records the limits in force when it was computed.

---

## 1. Contact angle (sessile drop)

### 1.1 Image acquisition
The browser captures a full-resolution frame from the selected camera (`getUserMedia` → canvas → PNG). The
frame is sent to the local backend only when the user presses *Capture & Analyse* / *Re-analyse* / *Save*.
The saved original is byte-identical to the captured PNG; its SHA-256 is stored and re-verified on every read.

### 1.2 Pipeline (`backend/app/services/wettability/detection.py`, `proposals.py`)
Automatic detection is a search, not a single recipe: several ways of finding the drop are combined with several ways of finding the surface, each combination is measured with the same geometry, and the best supported one is reported. An image that shows no measurable drop still fails with a clear message: an angle is never returned just because some contour exists.

1. **Validation** – decodes PNG/JPEG/BMP/TIFF, applying the orientation tag that phones write; rejects images < 32 px per side or > 50 MP; 16-bit images are scaled to 8 bit.
2. **ROI** – optional user rectangle; all coordinates are reported in full-image pixels.
3. **Working image** – photographs are resized so the long side is at most 1600 px, tiny images are enlarged up to 3×, and coloured labels or lines from other software are painted out of the working copy. All coordinates are mapped back to the original image.
4. **Foreground and baseline proposals** –
   * *Foreground fields*: global threshold (Otsu unless the user sets one; polarity from the top rows), colour distance from a fitted smooth background (handles vignettes, gradients and colour), and the region enclosed by strong edges (transparent drops).
   * *Baselines, in order of trust*: the specimen surface as a straight two-sided brightness step across the image (averaging along the line makes it indifferent to grain, scratches and roughness), the top profile of the foreground fitted by RANSAC, the mirror axis between a drop and its reflection, a flat lower edge of the drop, and long straight edges.
   * *Traced outline*: edge normals of a circle meet at its centre, so pairs of edge points vote for circles that pass over their own top. The real boundary is then followed around each circle as the smoothest strong path, re-centring the circle on each pass, so refraction rims inside a transparent drop cannot pull single rays off course. The baseline for an outline is the lowest two-sided surface step that the outline comes down to, else the line through the ends of the outline.
   * *Scoring*: each candidate is scored on how the baseline was found (surface on both sides > mirror or flat edge > strongest edge), the circle residual, left-right agreement, local-tangent versus circle agreement, how much of the outline is really visible and how much of the drop base is extrapolated. A baseline with the outline visibly continuing below it is penalised, because it cuts through the drop. A surface line on both sides of a well-shaped drop ends the search early. The search is deterministic: the same image and engine always give the same result.
   * *Rotation*: if nothing is found the right way up, the image is tried turned by 90/180/270°, and that is accepted only on strong evidence.
5. **Baseline frame** – every pixel is expressed as (u, v): u along the baseline (left→right), v perpendicular, positive towards the droplet. Image y points down; the frame handles this and any tilt up to 45°.
6. **Droplet region** – the largest connected foreground component lying above the baseline and touching it, after a small opening that cuts slivers of rough surface. A dispensing needle (a narrow stem running down from the top) is ignored in the fits. A component touching the left/right ROI border is refused (clipped droplet, or baseline below the surface if both sides are touched). Touching the top border raises a warning. Boundaries that are not shaped like a droplet (circle residual above 8 % of the radius, or almost flat) are rejected.
7. **Boundary** – external contour, then each point is moved to the sub-pixel location where the blurred intensity crosses the threshold (or to the steepest edge for the edge field) along the local intensity gradient (bilinear sampling ±2.5 px). Traced outlines are already sub-pixel. Points within `exclude_px` (default 3 px) of the baseline are excluded from fitting because blur rounds the drop/substrate corner.
8. **Contact points** – initial estimates are the extreme u of droplet pixels within 4.5 px of the baseline (or user-placed points); they are refined by the fits.
9. **Local tangent (default reported method)** – for each side, boundary points within the fitting radius (default 20 % of the droplet's maximum width, 12–600 px) are rotated into their principal-axis frame and fitted with a quadratic t = q(s). The fitted curve is intersected with the baseline (v = 0) and differentiated there. Fitting in the rotated frame keeps the problem well conditioned from very low to very high angles.
10. **Spherical-cap fit** – algebraic (Kåsa) circle fit refined by geometric least squares on the free boundary points, with up to three rounds of outlier trimming. For a traced outline this is the reported method, because few boundary points survive near the contact line. θ = arccos(−v_c / R), where v_c is the centre height above the baseline. The fit is *rejected* if the circle does not intersect the baseline, if RMS residual / R exceeds `circle_max_rel_rms` (1.5 %), or if its baseline intersections disagree with the local-tangent contact points by more than max(3 px, 3 % of contact width).
11. **Angle convention** – the angle inside the liquid between the baseline (pointing into the drop) and the tangent; left and right are measured independently (θ_L uses the +u direction, θ_R the −u direction), so they are never swapped and asymmetric drops are reported as such.
12. **Waist check** – an interior minimum of droplet width above the baseline indicates that a reflection is included below the real contact line; a warning and a suggested baseline are returned.
13. **Status** – `failed` (no angle; explicit error), `needs_correction` (an angle exists but a diagnostic failed, e.g. |θ_L − θ_R| > 10°, or the evidence is low), or `ok`.
14. **Detection evidence** – `high` needs a surface seen on both sides and a clearly visible outline; `medium` means part of the outline or surface is unclear, and a warning asks the user to confirm the overlay; `low` always means `needs_correction`. This is a heuristic statement about the image, not an uncertainty.

### 1.3 Measured performance
See [CONTACT_ANGLE_EVALUATION.md](CONTACT_ANGLE_EVALUATION.md). This is a geometric algorithm developed and tested against rendered images and published photographs. It is not a trained neural network.

### 1.4 Manual correction
* Moving the baseline or contact points, changing threshold, polarity or fitting radius re-runs the same pipeline with those inputs and records the method `manual_corrected`. The fully automatic result for the same image and ROI is computed and stored separately in `auto_result`, and an audit event records both values.
* **Manual tangent** mode computes θ from user-placed contact and tangent points only: θ = atan2(t_v, ±t_u) in the baseline frame. Used when segmentation is impossible (e.g. very low contrast).
* Re-analysis of a saved record (PATCH) keeps the previous values in the audit history; the original image is never modified.

### 1.5 Quality indicators
Saturated-pixel fraction, contrast, baseline fit RMS and tilt, number of boundary points, local-fit RMS per side, circle residual/R, left–right difference, local-tangent vs circle agreement, manual-correction flag and reported method. **These are heuristic diagnostics, not a calibrated measurement uncertainty.** Repeatability must be established from repeated drops (report mean ± SD of independent drops in the project report).

### 1.5 Classification
Using the mean angle at display precision (0.1°): < 90° *hydrophilic*, > 90° *hydrophobic*, exactly 90.0° *at hydrophilic/hydrophobic boundary*. A repeat measurement is recommended when the mean lies within the configurable display tolerance (default ±2°, a UI setting, not a physical uncertainty) of 90°, or when θ_L and θ_R lie on opposite sides of 90°.

> Contact-angle classification describes the measured water wettability. It does not independently establish corrosion resistance or corrosion rate.

### 1.6 Verification on synthetic images
Synthetic silhouettes with angles known by construction (two circular arcs sharing the apex; 4× supersampled; noise; optional tilt/low contrast) are analysed in `backend/tests/test_wettability.py`. Observed errors were ≤ 0.5° for 20–150° and about 1–2° near 170° for the local-tangent method. The test tolerance is 1.5°. **This is accuracy on ideal synthetic geometry only**; real images add optics, focus, lighting, reflections, gravity flattening and operator effects. See `HARDWARE_VALIDATION.md`.

---

## 2. Electrochemistry

### 2.1 Import
* Encoding: UTF-8 (with or without BOM), UTF-16 (BOM or null-byte detection), otherwise cp1252 (with replacement); files that look binary are refused.
* The parser finds the longest block of consecutive rows with a constant field count and ≥ 60 % numeric cells under each candidate delimiter (tab, comma, semicolon, whitespace; decimal comma supported for non-comma delimiters). The header is the non-numeric line above it; an optional units row (Gamry style) is recognised. Key/value lines before the header become metadata. Missing cells, duplicated rows and additional numeric blocks are reported.
* Column roles and units are **suggested** from header text (e.g. `Ewe/V`, `<I>/mA`, `Vf`, `Im`, `Z' (Ω)`, `-Im(Z)/Ohm`) but must be confirmed. **A mapped column without a unit is refused**; units are never assumed.
* Canonical units after import: s, V, A, A/cm², Hz, Ω, degrees. Anodic current positive (an import option inverts anodic-negative files). Z = Z′ + jZ″ with Z″ stored physically (negative for capacitive response); a column holding −Z″ must be declared.
* Current density i = I / A uses the exposed area entered at import or recorded on the specimen; the area and its source are stored with the run. LPR/polarisation imports with total current and no area are refused.
* The original file is stored unmodified with its SHA-256; a processed CSV in canonical units is stored separately.

### 2.2 Open-circuit potential (OCP)
Mean, sample SD, final value and drift (least-squares slope of E(t), mV/min) over a user-selected interval (default: final 20 % of the record). A warning is issued when |drift| > 1 mV/min (configurable) or the reference electrode is not recorded. **No corrosion current or rate is ever derived from OCP**, even if material properties are supplied.

### 2.3 Linear polarisation resistance (LPR)
E_corr is the interpolated zero-current potential (or user value). Within the window (default ±10 mV, user adjustable or explicit E limits) E = R_p·i + c is fitted by least squares on current density, so **R_p = (dE/di) at E ≈ E_corr in Ω·cm²**. R_p is marked unreliable if R² < 0.99, the slope is not positive, or there are < 5 points; a window wider than ±25 mV triggers a linearity warning.
**i_corr = B / R_p** is calculated only when a Stern–Geary coefficient B (or Tafel slopes β_a, β_c with B = β_aβ_c / (2.303(β_a+β_c))) is supplied **together with its source**. No default B exists.

### 2.4 Potentiodynamic polarisation (Tafel extrapolation)
* Plotted as E versus |i| on a logarithmic axis; zero-current points are excluded from the logarithm and counted; signs are preserved for the anodic/cathodic split.
* Each branch is fitted as E = a + β·log10|i| over an overpotential window relative to the observed zero-current potential (anodic: i > 0, cathodic: i < 0).
* Without user regions the software searches windows starting ≥ 50 mV from E_corr and proposes the best-R² window satisfying the criteria. **Proposed regions are labelled `auto_proposed`, the result is flagged for review, and such results are excluded from ML datasets until the user confirms regions.**
* A branch is unreliable when R² < 0.98, it spans < 1 decade of current, has < 8 points, or its slope has the wrong sign. Warnings: region starting < 50 mV from E_corr (mixed control), Tafel-intersection E_corr differing from the observed zero-current potential by > 20 mV, β outside 20–400 mV/dec (heuristic plausibility range).
* The intersection of the two lines gives log10 i_corr and E_corr; β_a, β_c and the derived B are reported. Results from an unsuitable curve are stored with `valid = false`. ASTM compliance is **not** claimed.

### 2.5 Corrosion penetration rate
**CR [mm/y] = 0.00327 · i_corr [µA/cm²] · EW [g/eq] / ρ [g/cm³]**, calculated only from a valid i_corr with EW and ρ **and their source**. Built-in profiles exist only for pure metals (Fe→Fe²⁺, Al→Al³⁺, Cu→Cu²⁺, Zn→Zn²⁺, Ni→Ni²⁺, Mg→Mg²⁺: EW = standard atomic weight / n; handbook densities); alloys require user values and trigger a composition/valence warning. Assumptions recorded: uniform corrosion, Faradaic dissolution with the stated EW, i_corr representative of the exposure.

### 2.6 EIS
Nyquist (−Z″ vs Z′), Bode |Z| and phase. Checks: positive frequencies (else refused), duplicate/non-monotonic frequencies, consistency of supplied |Z| (5 %) and phase (2°) with values computed from Z′, Z″, positive Z″ at the lowest frequency. Descriptors: |Z| at the lowest frequency (and area-normalised), Z′ at the highest frequency (≈ solution resistance only if the high-frequency limit was reached), frequency span. **No corrosion rate is derived from EIS.** Equivalent-circuit fitting is not implemented.

### 2.7 Verification
`backend/tests/test_electrochemistry.py` checks unit conversions and the CR formula by hand calculation, R_p against the analytic Butler–Volmer value B/i_corr (2 %), Tafel recovery of β_a = 60 mV/dec, β_c = 120 mV/dec, i_corr = 5 µA/cm² (3–5 %), refusal of unsuitable curves, OCP refusal, EIS |Z| against the analytic Randles–CPE value, parser behaviour on comma/tab/semicolon/decimal-comma/whitespace files and malformed inputs.

---

## 2A. Arduino rig (`backend/app/services/electrochemistry/arduino.py`)

The rig compares a good and a corroded electrode with ACS712 Hall current sensors and LM393 modules on a 10-bit Arduino ADC. **It is not a potentiostat:** it does not sweep potential, so i_corr, Tafel slopes and R_p cannot be obtained from it, and none are reported.

* **Parsing** – Serial Monitor text is read line by line (timestamps ignored, mV and mA scaled, bare verdict lines accepted). Repeated cycles are averaged and their real scatter is reported. Lines that are not understood are listed, never guessed.
* **Resolution** – one ADC step is 4.888 mV at 5 V, which is 26.4 mA for the 185 mV/A sensor. The ACS712-05B datasheet gives about 21 mV peak-to-peak noise at 2 kHz, about 114 mA. The sensor variant is identified from the printed numbers. A difference below the resolution floor is reported as "no difference", which is what the device's HEALTHY verdict is checked against.
* **Faraday estimate (Calculated)** – CR [mm/y] = 0.00327 · (I/A) [µA/cm²] · EW / ρ. It assumes that all of the measured current dissolves metal from the stated area, so it is an upper bound, shown with a range from the sensor resolution. A value far above natural corrosion currents is flagged as driven current.
* **Weight loss (Calculated from measured masses)** – CR [mm/y] = 8.76×10⁴ · W / (A · T · D), the ASTM G31 form, with W in g, A in cm², T in h and D in g/cm³. This is the reliable rate for this rig and the only one that gets a severity class (NACE SP0775 bands).
* **Area and material are never defaulted.** Without them no rate is shown. Rig metrics use `rig_` names, so they are never mixed with potentiostat values or ML targets.

---

## 3. Machine learning

### 3.1 Records
One row per electrochemical run with a **valid, non-superseded** target metric (i_corr, corrosion rate or R_p; never mixed). Excluded: invalid/unreliable metrics and Tafel results whose regions were only auto-proposed. Contact-angle feature = mean of the specimen's accepted contact-angle measurements, preferring those linked to the same experiment. Real and demo records are never mixed.

### 3.2 Features
Permitted inputs: material, surface preparation, electrolyte, concentration (single unit), temperature, roughness Ra, and — only in the enhanced configuration — contact angle. Requests containing electrochemical outputs (i_corr, R_p, β, B, E_corr, CR, |Z|, OCP…) are rejected as target leakage.

### 3.3 Readiness policy (configurable)
* *insufficient* – fewer than 4 independent specimen groups, no target variation, no contact-angle data or no contact-angle variation, mixed concentration units: training disabled.
* *exploratory* – fewer than 15 groups or synthetic data: training allowed, results labelled exploratory.
* *adequate* – ≥ 15 groups and real data: "validated evaluation" badge.
These thresholds are a documented policy, not a universal sample-size rule.

### 3.4 Evaluation
* `GroupKFold` by specimen ID (shuffled with the recorded seed), k = min(5, number of groups): a specimen's repeated measurements are never split between training and test.
* Every configuration uses the **same folds**: mean-only, linear regression and random forest (300 trees), each with baseline features and with baseline + contact angle.
* Preprocessing inside scikit-learn pipelines, fitted per training fold: numeric median imputation (+ standardisation for linear models), categorical constant imputation + one-hot encoding with unknown categories ignored.
* Metrics from out-of-fold predictions: MAE, RMSE, R² (reported as N/A with a reason when undefined), fold-to-fold SD of MAE; in log10 units when the log transform is selected (plus MAE in original units).
* Paired comparison per model family: ΔMAE (enhanced − baseline) and the number of folds improved. The interpretation text never states that contact angle "helps" for exploratory or synthetic datasets.

### 3.5 Persistence and prediction
The final pipeline (fitted on all rows) is saved with joblib; its SHA-256, features, training domain, dataset hash, seed, split, metrics and software versions are stored. Loading checks path containment and hash. Predictions are labelled **PREDICTED**, report the model's out-of-fold error, and warn about unknown categories, imputed inputs, values outside the training range, exploratory datasets and synthetic training data. No prediction interval is reported because none has been validated.

---

## 4. Demonstration data
Generated on explicit request only, flagged `is_demo`, prefixed `DEMO-`. Synthetic contact angles (45–135°) and corrosion currents (log-uniform 0.5–20 µA/cm²) are drawn **independently**, so the demo cannot exhibit a wettability–corrosion relationship. Demo data test software behaviour only.
