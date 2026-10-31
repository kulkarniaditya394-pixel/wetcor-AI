# Hosting on Netlify (analysis runs in the visitor's browser)

Netlify cannot run Python, so the hosted site runs the **same analysis code in the browser** using Pyodide (Python
compiled to WebAssembly, loaded from the jsDelivr CDN) inside a web worker. Visitors can:

* **Wettability Lab** — upload a droplet photo (or use their camera over HTTPS). OpenCV measures the left/right/mean
  contact angle, draws the baseline/boundary/tangents, and classes the surface hydrophilic / hydrophobic / boundary.
  Manual baseline, ROI, threshold and manual-tangent correction work as in the local app.
* **Corrosion Lab, Arduino rig** — paste the Serial Monitor output or type the values, and get the current comparison, what the hardware can resolve, whether the device verdict holds, and the corrosion rate once the area and material are entered.
* **Corrosion Lab, potentiostat** — drop a potentiostat export (CSV/TSV/TXT), map columns and units, then get OCP, LPR,
  polarisation (Tafel) or EIS results: i_corr, β_a/β_c, E_corr, R_p, corrosion rate (with material properties and their
  source), Nyquist/Bode, warnings, assumptions. Download results as CSV or print to PDF.
* **Showcase** — one pre-computed example test.

Files never leave the browser: there is no server and nothing is uploaded or stored.

## Not available on the hosted site
Specimen/experiment database, saved measurements, reports built from saved records, ML Studio. They store data and
train models on your own computer, so they remain in the local app (`setup-windows.ps1`, `run-local.ps1`).
The hosted pages for them explain this.

## Deploy
1. Netlify → *Add new project → Import an existing project → GitHub* → `wetcor-AI`, branch `main`.
2. Settings (also in `netlify.toml`): **Base directory** `frontend`, **Build command** `npm run build`,
   **Publish directory** `out` (not `.next`). No environment variables needed: static mode switches on by itself when
   `NETLIFY=true`.
3. Deploy. `/` shows the showcase; `/wettability` and `/corrosion` run the engine.

## How it works
* `frontend/next.config.ts` exports the site as plain HTML/CSS/JS (`output: "export"`) in static mode.
* `frontend/public/engine/worker.js` (module worker) loads Pyodide 314.0.7 + NumPy, SciPy, pandas, OpenCV (≈45 MB on
  the first visit, cached by the browser afterwards) and `engine/app.zip`.
* `app.zip` holds the pure-analysis modules from `backend/app` (no FastAPI, database or file storage). Build it with
  `backend\.venv\Scripts\python scripts\build_engine_bundle.py` after changing any of them; a backend test fails if the
  committed zip is stale or imports server-only code.
* `backend/app/services/quick.py` is the single implementation used both by the local API (`/api/corrosion/quick`,
  `/api/wettability/analyze`) and by the browser engine, so results are identical. The wettability and electrochemistry
  test suites were also run inside Pyodide (56 passed). OpenCV differs (4.11 here, 5.0 locally), so on hard photos the two can differ by a few degrees; see CONTACT_ANGLE_EVALUATION.md.
* `frontend/lib/engine.ts` maps the app's REST calls onto engine functions, so the pages are the same code in both modes.
* The showcase snapshot is `frontend/public/showcase-static/` (`scripts/export_static_showcase.py`).

## Requirements and limits
* The visitor's browser needs internet access to `cdn.jsdelivr.net` (to fetch Pyodide) and a modern browser
  (module workers: Chrome/Edge/Brave 80+, Firefox 114+, Safari 15+). The first visit takes roughly 10–60 s to load;
  a clean image then takes under a second and a hard photo 2 to 4 s.
* Camera capture needs HTTPS (Netlify provides it).
* Large images/files are limited by browser memory only.

## Local app is unaffected
Static mode is on only when `NEXT_PUBLIC_STATIC_DEMO=1` or `NETLIFY=true`. To try the export locally:
`cd frontend; $env:NEXT_PUBLIC_STATIC_DEMO=1; npm run build` (output in `out/`), serve `out/` with any static server,
then delete `out` and `.next` before running `run-local.ps1`.
