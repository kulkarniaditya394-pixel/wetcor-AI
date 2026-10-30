# Manual hardware validation (not automated)

Automated tests mock the camera and use synthetic files. Before using results in the project report, perform and
record these checks on the actual laboratory setup.

## A. USB camera
1. `.\run-local.ps1`, open `http://localhost:3100/wettability` in Chrome or Edge.
2. *Start camera* → allow permission → select the USB camera → choose resolution. Record the delivered resolution shown.
3. Unplug the camera while live → "Camera disconnected" message; replug → *Refresh devices* → *Start camera*.
4. Open the camera in another app → *Start camera* → "Camera busy" message.
5. Navigate away from the Wettability Lab → camera LED turns off (tracks stopped).

## B. Contact-angle repeatability and trueness
1. **Geometric check**: print or photograph a calibration target with known angles (e.g. machined 60°/90°/120° wedges or a precision ball on a flat for 90°) at the droplet position; analyse with *Manual tangent* and automatic modes; record the differences.
2. **Repeatability**: ≥ 5 independent drops of the same liquid volume on one specimen; record mean ± SD of θ_mean and of |θ_L − θ_R|.
3. **Reproducibility**: repeat on another day / after re-levelling.
4. **Reference comparison** (if available): measure the same specimens on a commercial goniometer; report bias and limits of agreement.
5. Keep camera horizontal with the specimen surface; reflections below the contact line trigger the waist warning — move the baseline to the narrowest point.

## C. Potentiostat import
1. Export one OCP, one LPR, one polarisation and one EIS measurement from the instrument software in its text format.
2. Import each; confirm the suggested mapping and especially the **current unit** and **sign convention** against the instrument manual.
3. Compare R_p / i_corr / β with the instrument software's own fit using the same regions; record differences.
4. Verify that the raw-file SHA-256 shown on the run page matches `Get-FileHash <file> -Algorithm SHA256` of the exported file.

## D. Record
Store results of A–C in the project log (date, operator, camera model/resolution, potentiostat model/software version).
