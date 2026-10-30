# Data dictionary

SQLite database `data/database/wetcor.sqlite3`. Timestamps are UTC. `is_demo = true` marks synthetic demo records.

## specimens
| Field | Type | Unit | Meaning |
|---|---|---|---|
| id | int | | Primary key |
| code | text, unique | | Specimen ID (`DEMO-` prefix reserved) |
| material | text | | Material / grade |
| batch_source | text | | Batch or supplier |
| dimensions | text | | Free text, e.g. `50 x 25 x 2 mm` |
| surface_preparation | text | | Preparation or treatment |
| roughness_ra_um | float | µm | Optional Ra |
| exposed_area_cm2 | float | cm² | Electrode area used for current density |
| notes, created_at, updated_at, is_demo | | | |

## experiments
| Field | Type | Unit | Meaning |
|---|---|---|---|
| code | text, unique | | Experiment ID |
| specimen_id | FK → specimens (RESTRICT) | | |
| experiment_type | text | | wettability / corrosion / combined |
| performed_at | datetime | | |
| operator, instrument, reference_electrode, procedure, notes | text | | |
| electrolyte | text | | e.g. NaCl |
| concentration_value / concentration_unit | float / text | as recorded | |
| temperature_c | float | °C | |
| status | text | | planned / in_progress / complete / invalid |

## artifacts
Every stored file. `kind` ∈ raw_image, overlay_image, raw_data, processed_data. `stored_path` is relative to `data/` and server-generated; `original_filename` is kept only as metadata. `sha256`, `size_bytes`, `content_type`, `specimen_id`, `experiment_id`, `meta` (JSON), `is_demo`.

## contact_angle_runs
| Field | Unit | Meaning |
|---|---|---|
| image_artifact_id / overlay_artifact_id | | Original image (never modified) and annotated overlay |
| method | | auto_polynomial, auto_circle, manual_corrected, manual_tangent |
| status | | accepted / rejected (+ rejection_reason) |
| left_deg, right_deg, mean_deg | ° | **Measured** angles (null when analysis failed) |
| classification | | hydrophilic / hydrophobic / boundary |
| analysis_params | JSON | ROI, baseline, contact points, threshold… used |
| diagnostics | JSON | Quality indicators, fits, geometry, limits in force |
| warnings | JSON | |
| auto_result | JSON | Purely automatic result kept when corrections were applied |
| algorithm_version | | e.g. ca-1.0.0 |
| liquid, droplet_volume_ul (µL), captured_at, measured_at, notes | | |

## corrosion_runs
| Field | Meaning |
|---|---|
| raw_artifact_id / processed_artifact_id | Original export / canonical-unit CSV |
| method | ocp, lpr, pdp, eis |
| column_mapping, units | JSON: role → column, role → unit (as selected by the user) |
| import_meta | Encoding, delimiter, header line, file metadata, sign conventions |
| parser_warnings | |
| exposed_area_cm2 / area_source | Area used for i = I/A and where it came from |
| reference_electrode, instrument, n_points, analysis_status, notes | |

Canonical processed columns: `time_s` (s), `potential_V` (V), `current_A` (A), `current_density_A_cm2` (A/cm², anodic positive), `frequency_Hz`, `z_real_ohm`, `z_imag_ohm` (Z″, physical sign), `z_mod_ohm`, `phase_deg`.

## corrosion_analyses
One execution of an analysis: `method_version`, `params`, `result` (fit lines, windows, warnings, notes), `status` (ok / limited / invalid), `superseded`.

## derived_metrics
**Calculated** values: `name`, `label`, `value`, `unit`, `origin` = calculated, `formula`, `parameters` (incl. sources of B / EW / ρ, fit windows, selection), `assumptions`, `warnings`, `valid`, `superseded`, `analysis_id`.

| name | unit | method |
|---|---|---|
| ocp_mean, ocp_final | V | OCP |
| ocp_std | mV | OCP |
| ocp_drift | mV/min | OCP |
| ocp_duration | s | OCP |
| e_corr_zero_current | V | LPR / PDP |
| rp | Ω·cm² | LPR |
| i_corr | µA/cm² | LPR (with B) / PDP |
| e_corr_tafel | V | PDP |
| beta_a, beta_c | mV/dec | PDP |
| stern_geary_B | mV | PDP |
| corrosion_rate | mm/y | LPR / PDP with EW, ρ |
| z_mod_low_f, z_real_high_f | Ω | EIS |
| z_mod_low_f_area | Ω·cm² | EIS |
| eis_decades | decades | EIS |

## ml_runs
One row per model configuration; rows of one training share `comparison_id`. Fields: `name`, `model_family` (mean / linear / random_forest), `feature_set` (none / baseline / wettability), `features`, `target`, `target_unit`, `target_transform`, `dataset_hash`, `n_records`, `n_groups`, `split_strategy`, `n_splits`, `seed`, `metrics` (MAE, RMSE, R² or null + note, per-fold), `oof_predictions` (**predicted**), `feature_domain`, `readiness_level`, `includes_demo`, `model_path`, `model_sha256`, `software_versions`, `warnings`.

## audit_events
`entity_type`, `entity_id`, `action` (create, update, manual_correction, reanalysis, analysis, import, delete, train, load, reset), `summary`, `details` (before/after values), `created_at`.

## app_settings
Key `analysis`: JSON of the analysis limits (see METHODS.md and the Settings page).
