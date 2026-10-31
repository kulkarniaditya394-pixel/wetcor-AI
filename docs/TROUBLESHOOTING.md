# Troubleshooting

Logs: `.run\backend.log`, `.run\backend.err.log`, `.run\frontend.log`, `.run\frontend.err.log`.

| Problem | Diagnosis and fix |
|---|---|
| **Node.js or Python missing** | `node --version` (need ≥ 20.9), `python --version` (3.11/3.12). Install from nodejs.org / python.org (tick *Add to PATH*), open a **new** PowerShell, rerun `setup-windows.ps1`. The Microsoft Store `python` alias is ignored. |
| **Scripts blocked** ("running scripts is disabled") | `powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1`, or once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| **pip install fails** | Check internet/proxy; `backend\.venv\Scripts\python -m pip install -r backend\requirements.txt` to see the failing package. On Python 3.14+ wheels may be missing: install 3.11/3.12 and delete `backend\.venv`, then rerun setup. |
| **npm install fails** | Delete `frontend\node_modules`, run `cd frontend; npm ci`. Behind a proxy set `npm config set proxy …`. |
| **Port already in use** | `run-local.ps1` refuses busy ports. Find the owner: `Get-NetTCPConnection -LocalPort 8100 \| Select OwningProcess`. Or use `.\run-local.ps1 -BackendPort 8200 -FrontendPort 3200` (frontend rebuilds automatically for the new API URL). |
| **"already appears to be running"** | Run `.\stop-local.ps1`; if a stale `.run\*.pid` remains after a crash it is removed by the stop script. |
| **Camera permission denied** | Browser address-bar camera icon → Allow, or `chrome://settings/content/camera` / `edge://settings/content/camera`; then *Start camera*. Windows: Settings → Privacy & security → Camera → allow desktop apps/browsers. |
| **USB camera not listed** | Reconnect, wait 5 s, *Refresh devices*. Device names appear only after permission is granted. Check Device Manager → Cameras. Try another USB port (avoid unpowered hubs). |
| **Camera busy** | Close Camera app, Teams, Zoom, OBS or another browser tab using it. |
| **"Camera API unavailable"** | Open `http://localhost:3100` (not a file path, not a LAN IP); use current Chrome/Edge/Firefox. |
| **Backend not responding / red status dot** | Is `run-local.ps1` running? Open `http://127.0.0.1:8100/api/health`. Read `.run\backend.err.log`. |
| **CORS / "Failed to fetch"** | Frontend must be opened on the port given to `run-local.ps1`; the backend allows only `localhost`/`127.0.0.1` at that port. Do not open the page from another computer. |
| **Contact-angle analysis fails** | The engine already tries several ways to find the drop and the surface. Read the error: nothing found → use a side-on image with the drop and surface in view, crop to one drop with the ROI, or drag the baseline onto the surface; clipped droplet → move camera/ROI; low contrast → improve back-lighting, set threshold manually, or use *Manual tangent* mode. |
| **Malformed potentiostat export** | Preview shows the parsed block; export as CSV/TXT from the instrument software. Binary formats (.mpr, .ids, .nox) are not read. |
| **Unknown column names** | Map the columns manually in step 3; every role can be assigned to any column. |
| **Missing units** | Pick the unit beside each mapped column; import is refused until every mapped column has one. Check the instrument manual for current units (A vs mA vs µA). |
| **Invalid Tafel analysis** | Curve must show linear E–log|i| regions ≥ 1 decade, starting ≥ 50 mV from E_corr. Adjust regions; if none exist (diffusion control, passivity) the curve is unsuitable — use LPR with a documented B. |
| **Missing material properties** | Corrosion rate needs EW and density **with a source**; pick a pure-metal profile or enter alloy values (ASTM G102 method) with their source. |
| **ML dataset too small** | ML Studio lists blocking reasons; at least 4 independent specimens with confirmed i_corr and varying contact angle (configurable in Settings). |
| **Model cannot be loaded** | "hash does not match" / "missing": the file in `models\` was changed or deleted. Retrain the comparison. |
| **Database migration failure** | A backup `data\database\wetcor-v<N>-backup-*.sqlite3` is made before any migration; restore it by copying over `wetcor.sqlite3`. "no schema version" means the file is not a WETCOR database: move it away. |
