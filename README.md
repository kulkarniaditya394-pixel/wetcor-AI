# WETCOR AI — Wettability and Corrosion Intelligence Platform

An experimental intelligence platform for quantitative surface-wettability analysis, electrochemical corrosion
characterisation and machine-learning-assisted corrosion prediction. Built as the software companion of a
B.Tech Mechanical Engineering (Robotics & Automation) final-year project.

**Research question.** Can surface wettability, measured as the water contact angle, add useful predictive
information about the electrochemical corrosion behaviour of metallic specimens?

WETCOR AI runs entirely on one Windows laptop: a FastAPI backend and a Next.js frontend on `127.0.0.1`, a
SQLite database and local files. No cloud API, no online AI service and no upload of laboratory data.

---

## What it does

| Area | Function |
|---|---|
| **Showcase** | One complete, pre-computed test to open during a presentation: inputs, a real goniometer frame analysed by WETCOR AI next to the instrument's own reading, OCP and polarisation results with formulas. Loaded on request; see `data/showcase/README.md` (image licence and how to swap in your own steel-plate test). |
| **Overview** | Counts, data completeness, recent experiments and activity, all computed from the local database. Demo data are counted separately. |
| **Wettability Lab** | USB-camera preview (`getUserMedia`), device and resolution selection, **Capture & Analyse**, OpenCV sessile-drop analysis (baseline, contact points, sub-pixel boundary, local-tangent and spherical-cap fits), draggable baseline/contact/tangent handles, ROI, manual tangent mode, quality diagnostics, 90° classification, traceable saving. Image upload works when no camera is connected. |
| **Corrosion Lab** | Drag-and-drop import of CSV/TSV/TXT potentiostat exports, preview, explicit method selection (OCP, LPR, potentiodynamic polarisation, EIS), column and **unit** mapping, validation, plots, analysis with documented formulas, re-analysis history, raw and processed downloads. |
| **Experiments** | Specimens and experiments with search, sort, filters, pagination, linked measurements, files, history, guarded deletion and CSV export. |
| **ML Studio** | Dataset readiness report, five model configurations (mean-only, linear and random forest, each with and without contact angle) on identical **specimen-grouped** cross-validation folds, leakage guards, actual-vs-predicted plot, saved-model predictions with out-of-domain warnings. |
| **Reports** | Print-ready experiment and ML reports (Print → Save as PDF) and eight CSV exports, all traceable to database records and file hashes. |
| **Settings** | Service status, every analysis limit (with its meaning), load/reset of the clearly labelled synthetic demo workspace. |

Every value carries its origin: **Measured** (image/instrument), **Calculated** (documented formula) or
**Predicted** (fitted model). Synthetic records are flagged `DEMO — SYNTHETIC DATA` everywhere.

---

## Quick start (Windows 10/11)

Requirements (installed by you, not by the script): **Node.js LTS 22 or 24** (≥ 20.9) and **Python 3.11 or 3.12**
(3.13 accepted). Tested with Node 24.17.0, npm 11.13.0, Python 3.11.15 on Windows 11.

```powershell
cd "path\to\wetcor-ai"
powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

Open **http://localhost:3100** in Chrome or Edge. In *Wettability Lab* press **Start camera** and allow camera
access. Stop everything with `.\stop-local.ps1`.

`-ExecutionPolicy Bypass` only affects that one command; alternatively run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once. Options: `run-local.ps1 -BackendPort 8200 -FrontendPort 3200`,
`run-local.ps1 -Dev` (hot-reload development server).

For a presentation, open **Showcase → Load showcase example** once; afterwards the finished test opens instantly.
No laboratory data yet? *Settings → Load demo data* creates 10 synthetic specimens with images, OCP/LPR/
polarisation/EIS runs and analyses. Synthetic sample files for the import wizard and image upload are in
`data/demo/`.

---

## End-to-end laboratory workflow

1. **Experiments → New specimen**: specimen ID, material, preparation, exposed area (cm²).
2. **New experiment** for that specimen: electrolyte, concentration, temperature, reference electrode, instrument.
3. **Wettability Lab → Start camera** → focus on the back-lit droplet → **Capture & Analyse**.
4. Check the overlay: cyan baseline, amber contact points/tangents, green boundary. Drag handles or set an ROI and
   **Re-analyse with corrections** (recorded as `manual_corrected`; the automatic result is kept separately).
   For very poor images use *Manual tangent* mode.
5. Select specimen and experiment, **Save measurement** (original PNG + SHA-256, overlay stored separately).
6. **Corrosion Lab** → drop the potentiostat export → choose method → map columns and units → specimen → **Import run**.
7. On the run page set the analysis parameters (fit window, Tafel regions, Stern–Geary B with source, material
   EW/density with source) → **Analyse**. Results show formula, assumptions, validity and warnings.
8. **Experiment page → Experiment report** for a traceable, printable record.
9. With enough independent specimens, **ML Studio → Train & compare**; open the ML report.
10. **Reports** → CSV exports for the project report.

---

## Architecture

```text
Browser (Next.js 16 / React 19 / Tailwind 4 / Plotly)  --HTTP JSON-->  FastAPI (127.0.0.1:8100)
  camera via getUserMedia; frames sent only on Analyse                  ├─ wettability: OpenCV + NumPy/SciPy geometry
                                                                         ├─ electrochemistry: parser, units, OCP/LPR/Tafel/EIS
                                                                         ├─ machine_learning: scikit-learn pipelines, GroupKFold
                                                                         ├─ reporting: HTML + matplotlib SVG, CSV
                                                                         └─ SQLAlchemy → SQLite (data/database) + files (data/raw, data/processed)
```

```text
wetcor-ai/
├── backend/app/{api,core,database,schemas,services/{wettability,electrochemistry,machine_learning,reporting}}, main.py
├── backend/tests/            pytest: geometry, pipeline, electrochemistry, ML, database, API flows
├── frontend/app/{dashboard,wettability,corrosion,experiments,ml-studio,reports,settings}
├── frontend/{components,hooks,lib,schemas,tests}
├── data/{database,raw,processed,reports,demo,trash}   (git-ignored except demo samples)
├── models/                   saved model pipelines (git-ignored)
├── scripts/                  demo-file generator, API-doc exporter
├── docs/                     methods, data dictionary, storage, API, troubleshooting, hardware validation, test report
├── setup-windows.ps1  run-local.ps1  stop-local.ps1
└── PROJECT_STATUS.md
```

## Documentation

| File | Contents |
|---|---|
| [docs/METHODS.md](docs/METHODS.md) | Scientific methods, formulas, assumptions, quality limits, ML design |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Every table and field with units |
| [docs/STORAGE.md](docs/STORAGE.md) | Database, file layout, hashing, migrations, deletion, trust boundary |
| [docs/API.md](docs/API.md) | REST endpoints generated from the code (`docs/openapi.json`) |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Diagnostics for common problems |
| [docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) | Manual camera and potentiostat validation procedure |
| [docs/TEST_REPORT.md](docs/TEST_REPORT.md) | Recorded test results |
| [PROJECT_STATUS.md](PROJECT_STATUS.md) | What is done, what was run, limitations, next steps |

## Running the tests

```powershell
backend\.venv\Scripts\python -m pytest backend\tests -q
cd frontend; npm test; npm run typecheck; npm run build
```

## Scientific integrity rules built into the software

* No measurement, fit, rate, model score or experiment count is ever invented; empty states stay empty.
* OCP and EIS data are never converted into a corrosion rate. i_corr from LPR needs a documented Stern–Geary B;
  corrosion rates need equivalent weight and density **with their source**.
* Automatically proposed Tafel regions are flagged and excluded from ML datasets until the user confirms them.
* Contact-angle classification: < 90° hydrophilic, > 90° hydrophobic, exactly 90° boundary; near-90° results and
  left/right angles straddling 90° trigger a repeat-measurement recommendation. A hydrophobic surface is never
  described as corrosion resistant.
* Quality indicators are heuristic diagnostics, not calibrated uncertainties; synthetic-image accuracy is not
  real-world metrology accuracy.
* ML: specimen-grouped folds, preprocessing inside pipelines, leakage-feature rejection, readiness policy, no
  "validated" badge for small or synthetic datasets, predictions labelled as predictions.
