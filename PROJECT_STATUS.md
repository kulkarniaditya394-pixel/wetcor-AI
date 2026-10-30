# PROJECT STATUS — WETCOR AI 1.0.0 (2026-10-30)

## Implemented
* **Backend** (FastAPI, SQLAlchemy/SQLite, OpenCV, SciPy, scikit-learn): 48 REST operations (docs/API.md).
* **Wettability Lab**: camera selection/preview/capture, image upload, geometric contact-angle engine (auto baseline, sub-pixel boundary, rotated-frame local tangent, spherical-cap fit, diagnostics, waist/reflection warning), ROI, draggable/keyboard handles, manual tangent mode, `manual_corrected` with automatic result preserved, re-analysis history, rejection with reason, overlay export.
* **Corrosion Lab**: CSV/TSV/TXT parser (encodings, delimiters, decimal comma, Gamry unit rows, metadata), import wizard with explicit units, OCP / LPR / Tafel / EIS analyses with validity flags, Stern–Geary and material-property provenance, CR formula, superseded-analysis history, raw + processed downloads.
* **Experiment database**: specimens, experiments, artifacts with SHA-256, audit log, search/sort/filter/pagination, guarded deletion to trash, versioned migrations with backup.
* **ML Studio**: readiness policy, five configurations on identical specimen-grouped folds, leakage guard, out-of-fold metrics, paired comparison with conservative interpretation, persisted hash-checked models, predictions with domain warnings.
* **Reports**: print-ready experiment and ML reports (matplotlib SVG), 8 CSV exports.
* **Frontend**: Next.js 16 / React 19 / Tailwind 4 dark instrument UI; research-status dashboard; grouped navigation; empty, loading, warning and error states throughout; origin badges (Measured / Calculated / Predicted / Demo); responsive to 375 px.
* **Demo workspace** (explicit load/reset) and `data/demo` synthetic sample files.
* **Windows scripts**: setup, run (health-checked, auto-rebuild), stop (own processes only).

## Commands run (this build)
`setup-windows.ps1` · `run-local.ps1` (prod and `-Dev`) · `stop-local.ps1` · `pytest backend/tests` · `npm test` · `npm run typecheck` · `next build` · `scripts/generate_demo_files.py` · `scripts/export_api_docs.py`.

## Results
* Backend tests: **82 passed, 0 failed**. Frontend tests: **23 passed, 0 failed**. Typecheck passed. Production build **succeeded**.
* Setup, start and stop scripts verified on this machine (stop script bug found and fixed: it previously failed to match the backend command line).
* Details: docs/TEST_REPORT.md.

## Not tested / limitations
* **No real hardware was tested**: no USB camera (blocked in the test browser) and no real potentiostat files. Follow docs/HARDWARE_VALIDATION.md before relying on results.
* Contact-angle accuracy is demonstrated only on synthetic silhouettes (≤ 0.5° for 20–150°); real-world accuracy is unknown until calibrated.
* Automatic baseline needs the opaque specimen visible on both sides of the ROI; tilted-camera reflections need a manual baseline.
* No Young–Laplace (axisymmetric drop shape) fitting; large, gravity-flattened drops rely on the local-tangent method.
* EIS equivalent-circuit fitting not implemented. Binary instrument formats (.mpr, .nox, .ids) not read.
* No AI segmentation model (no suitable, licensed, labelled dataset identified); the geometric pipeline is the only method.
* ML training runs synchronously (fine for hundreds of records). No validated prediction intervals.
* Single-user, loopback-only; no authentication.
* No Playwright end-to-end suite; component tests and a manual browser walkthrough were used.

## Needed for laboratory validation
1. Camera calibration and repeatability study (HARDWARE_VALIDATION.md §B).
2. Cross-check of LPR/Tafel results against the potentiostat software on the same files.
3. At least 4 (exploratory) and ideally ≥ 15 independent specimens with confirmed i_corr and contact angles before interpreting the ML comparison.
