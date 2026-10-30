# Test report

Recorded 2026-10-30 on Windows 11, Python 3.11.15, Node 24.17.0. All fixtures are synthetic.

| Suite | Command | Result |
|---|---|---|
| Backend: contact-angle geometry + pipeline | `pytest backend/tests/test_wettability.py` | 29 passed |
| Backend: electrochemistry | `pytest backend/tests/test_electrochemistry.py` | 26 passed |
| Backend: ML | `pytest backend/tests/test_ml.py` | 10 passed |
| Backend: database / migrations | `pytest backend/tests/test_database.py` | 4 passed |
| Backend: API integration flows | `pytest backend/tests/test_api.py` | 13 passed |
| Backend: showcase example | `pytest backend/tests/test_showcase.py` | 1 passed |
| Backend: stateless/browser engine | `pytest backend/tests/test_quick.py` | 5 passed |
| **Backend total** | `backend\.venv\Scripts\python -m pytest backend\tests` | **88 passed, 0 failed** |
| Frontend unit/component | `cd frontend; npm test` (Vitest + Testing Library) | **30 passed, 0 failed** |
| Frontend typecheck | `npm run typecheck` | passed |
| Frontend production build | `npm run build` (Next.js 16.4.2) | passed, 14 routes |
| Windows setup | `setup-windows.ps1` | completed (venv, pip, npm ci, DB init, build) |
| Start / stop | `run-local.ps1`, `stop-local.ps1` | health-checked start; stop leaves 0 WETCOR processes |

## What the tests cover
* **Contact angle**: known angles 20–150° (both fits within 1.5°), 90° boundary and repeat flag, asymmetric 70°/100° not reversed, tilted baselines ±6–8°, low contrast warns, very low contrast refused + manual tangent recovers exactly, clipped droplet, no droplet, too few points, missing substrate requests a manual baseline, manual baseline recorded as `manual_corrected`, corrupt image, original bytes unchanged, no invented uncertainty, classification at 89.9/90.0/90.04/90.1°.
* **Electrochemistry**: unit and area conversions, unit refusal, current density, CR hand calculation, missing EW/density, B from Tafel slopes, parsers (comma, tab+units row, semicolon+decimal comma, whitespace, headerless, malformed/binary/empty), missing values and duplicates, mapping validation, OCP statistics and corrosion-rate refusal, LPR R_p vs analytic B/i_corr, B without source refused, wide window warning, missing area refused, Tafel recovery (β_a, β_c, i_corr, E_corr), auto-proposal flagged, unsuitable curve rejected, zero/negative current in semi-log, zero-crossing interpolation, EIS sign convention and |Z| vs analytic Randles-CPE, non-positive frequency refused.
* **ML**: MAE/RMSE/R² hand values and undefined R², leakage and invalid-target rejection, readiness levels incl. demo, grouped folds (each specimen held out exactly once), reproducibility with fixed seed, preprocessing fitted on training folds only (encoder categories and scaler means), model persistence, tamper and path-escape refusal, unknown categories / missing / out-of-range warnings, training refused when not ready.
* **Database**: persistence across restart, unique codes, foreign keys, migration applied once with backup, unversioned database refused.
* **API flows**: specimen CRUD/search/sort/pagination; experiment–specimen link check; image analyse → save → retrieve with byte-identical original; correction with separate automatic result and re-analysis history; failed analysis cannot be accepted; import preview/explicit units/import/analyse/re-analyse with supersession; OCP never yields CR; unsafe filename contained; linked dataset and CSV export match the database; experiment report with hashes; demo load → readiness → leakage refusal → train 5 configs → grouped folds → prediction warnings → ML report → reset; guarded deletion to trash; missing file reported; upload type checks.
* **Frontend**: navigation and active section; health indicator never shows connected on failure; dashboard empty state and demo separation; Plotly rendering; CSV export links; camera never auto-starts; denied / no-camera / unsupported states; start → full-resolution capture → stop; tracks released on unmount; keyboard correction of handles; tangent handles only in manual mode; specimen form validation and typed payload; experiment form; import wizard requires method and every unit before import; ML training disabled when insufficient; training failure shown.

## Manual browser verification (in-app browser pane, synthetic data)
Specimen and experiment creation; canvas-drawn 75° droplet uploaded → 75.0° measured; baseline handle moved by keyboard → `manual_corrected`, "automatic 75.0° → corrected 73.7°"; saved and opened (original image + SHA-256, separate overlay); Gamry-style polarisation file imported via the wizard with suggested mapping; auto-proposed regions flagged → accepted → β_a 59.8, β_c 119.3 mV/dec, i_corr 4.885 µA/cm²; demo workspace loaded; ML comparison trained on demo (exploratory); experiment report rendered; layout checked at 1440×900 and 375×812 (no horizontal scroll).

## Not run
* Real USB camera (the in-app browser blocks camera access; the denied state was observed). See HARDWARE_VALIDATION.md.
* Real potentiostat exports from the project's instrument.
* Playwright end-to-end tests (component tests + manual browser run used instead).

## Showcase example
Loaded from the UI and checked in the browser: inputs, source frame with attribution, WETCOR overlay, 111.2° (L 112.6°, R 109.9°, `manual_corrected`, automatic attempt failed on the mirror reflection) vs the instrument's own 114.6°, OCP and Tafel results (i_corr 7.82 µA/cm² vs synthetic truth 8). No horizontal overflow at 1024 px.

## Hosted static demo
Built with `NEXT_PUBLIC_STATIC_DEMO=1` and served with the backend stopped: `/` -> 307 `/showcase`; showcase renders (111.2 deg, both images, both plots, report link) with zero requests to the API; `/corrosion` shows the local-backend notice; bundled report opens. Not yet deployed on Netlify itself (Netlify's Next.js runtime build not exercised).

### Static export (replaces the Netlify Next.js runtime)
`NETLIFY=true npm run build` (no other variable) produces `frontend/out` (plain HTML/CSS/JS); served with a static server with Netlify-style pretty URLs: `/`, `/showcase` and the snapshot return 200, the showcase renders (111.2 deg, 2 images, 2 plots, CSS applied), `/corrosion` shows the local-backend notice, unknown paths return the 404 page. Local (non-static) build unchanged; arbitrary record IDs (`/wettability/5` etc.) still render.

## In-browser engine (hosted site)
* Wettability + electrochemistry suites run **inside Pyodide 314.0.7 under Node** (OpenCV 4.11, SciPy 1.18, pandas 3.0.2): 55 passed, 0 failed; dispatcher on the showcase files gave 111.23 deg and i_corr 7.824 uA/cm2, identical to the server.
* Exported site served by a static server, in a real browser: engine loads (~15 s first time), uploads of 65 deg and 112 deg droplets -> 65.0 deg hydrophilic / 112.1 deg hydrophobic in ~0.3 s; polarisation file -> wizard demands the electrode area, auto-proposed Tafel regions flagged, confirmed regions + Fe profile -> i_corr 7.735 uA/cm2, beta_a 69.7, beta_c 128.5 mV/dec, CR 0.0897 mm/y, with plot.
* Note: the in-app test browser refuses `importScripts` from a CDN inside workers, so the engine uses an ES-module worker (`import` of `pyodide.mjs`), which loaded fine.
* Not verified: a real Netlify deploy; camera capture on the hosted site (browser pane blocks the camera).
