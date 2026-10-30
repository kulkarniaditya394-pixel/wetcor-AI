# Database and file storage

```text
data/
├── database/wetcor.sqlite3          SQLite database (+ automatic pre-migration backups)
├── raw/images/                      original contact-angle images (never modified)
├── raw/instrument/                  original potentiostat exports (never modified)
├── processed/overlays/              annotated overlays
├── processed/data/                  canonical-unit CSV per corrosion run
├── demo/                            synthetic sample files + demo workspace artefacts
├── reports/                         reserved for saved reports
└── trash/                           files of deleted records (moved, not erased)
models/                              fitted model pipelines (*.joblib)
```

Override locations with `WETCOR_DATA_DIR` / `WETCOR_MODELS_DIR` (backend/.env). The data folder is never served as static files; files are downloaded only through `/api/artifacts/{id}/download`, which looks the path up by database ID, checks it stays inside `data/`, and re-verifies the SHA-256.

## Naming and integrity
Stored names are `<UTC timestamp>_<first 12 hex of SHA-256>_<sanitised original name>`. User filenames are reduced to `[A-Za-z0-9._-]`, stripped of directories, and cannot choose a folder (path traversal impossible). Files are opened with exclusive-create and never overwritten. Each artifact row stores SHA-256 and size; record pages show "hash verified" or the integrity error.

## Schema versioning
`PRAGMA user_version` holds the schema version. An empty database is created from the models; an existing one is copied to `wetcor-v<N>-backup-<timestamp>.sqlite3` and then upgraded by ordered migrations (`backend/app/database/session.py`, `MIGRATIONS`). The database is never recreated on start-up. A database with tables but no version is refused.

## Corrections and history
* Contact-angle corrections store the automatic result separately and write an audit event with old and new values; re-analysis keeps prior values in the audit history and a new overlay file.
* Electrochemical re-analysis marks the previous analysis and its metrics `superseded` (kept, viewable with `include_superseded=true`).
* Edits to specimens/experiments/settings record before/after values.

## Deletion
* Typed confirmation is required (record ID, `CA-<id>`, `EC-<id>`, `RESET-DEMO`).
* Specimens/experiments with linked records cannot be deleted (409). Nothing cascades.
* Deleting a measurement moves its files to `data/trash/` and records the full row in the audit log.
* *Reset demo workspace* deletes only `is_demo` records and their files.

## Trust boundary and privacy
* Backend binds to 127.0.0.1; CORS allows only the local frontend origins. Nothing is sent to external services; no telemetry.
* Uploads: size limit (25 MB default), extension/content-type checks, content parsed as image or text only; uploaded files are never executed.
* Model files are loaded only from `models/` after a hash check (joblib can execute code: never import foreign model files).
* Any program running under the same Windows user account can read `data/`; protect the account and back up the folder. No authentication is implemented because the service is loopback-only and single-user.
* Error messages returned to the browser do not include local paths or stack traces; details go to `.run/backend.err.log`.
