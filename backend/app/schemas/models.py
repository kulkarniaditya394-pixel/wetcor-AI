"""Typed request/response schemas for the REST API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CODE_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$"
Point = list[float]


def _real_code(v: str) -> str:
    if v.upper().startswith("DEMO-"):
        raise ValueError("The 'DEMO-' prefix is reserved for synthetic demo records.")
    return v


class Orm(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- specimens / experiments ----------------

class SpecimenBase(BaseModel):
    material: str = Field(min_length=1, max_length=120)
    batch_source: str | None = Field(None, max_length=200)
    dimensions: str | None = Field(None, max_length=200)
    surface_preparation: str | None = Field(None, max_length=200)
    roughness_ra_um: float | None = Field(None, ge=0, le=1000)
    exposed_area_cm2: float | None = Field(None, gt=0, le=10000)
    notes: str | None = Field(None, max_length=5000)


class SpecimenIn(SpecimenBase):
    code: str = Field(pattern=CODE_PATTERN)
    check_code = field_validator("code")(_real_code)


class SpecimenPatch(BaseModel):
    material: str | None = Field(None, min_length=1, max_length=120)
    batch_source: str | None = None
    dimensions: str | None = None
    surface_preparation: str | None = None
    roughness_ra_um: float | None = Field(None, ge=0, le=1000)
    exposed_area_cm2: float | None = Field(None, gt=0, le=10000)
    notes: str | None = None


class SpecimenOut(Orm, SpecimenBase):
    id: int
    code: str
    is_demo: bool
    created_at: datetime
    updated_at: datetime


ExperimentType = Literal["wettability", "corrosion", "combined"]
ExperimentStatus = Literal["planned", "in_progress", "complete", "invalid"]


class ExperimentBase(BaseModel):
    experiment_type: ExperimentType = "combined"
    performed_at: datetime | None = None
    operator: str | None = Field(None, max_length=120)
    electrolyte: str | None = Field(None, max_length=120)
    concentration_value: float | None = Field(None, ge=0)
    concentration_unit: str | None = Field(None, max_length=20)
    temperature_c: float | None = Field(None, ge=-50, le=300)
    instrument: str | None = Field(None, max_length=200)
    reference_electrode: str | None = Field(None, max_length=120)
    procedure: str | None = Field(None, max_length=10000)
    notes: str | None = Field(None, max_length=5000)
    status: ExperimentStatus = "in_progress"


class ExperimentIn(ExperimentBase):
    code: str = Field(pattern=CODE_PATTERN)
    specimen_id: int
    check_code = field_validator("code")(_real_code)


class ExperimentPatch(BaseModel):
    experiment_type: ExperimentType | None = None
    performed_at: datetime | None = None
    operator: str | None = None
    electrolyte: str | None = None
    concentration_value: float | None = Field(None, ge=0)
    concentration_unit: str | None = None
    temperature_c: float | None = Field(None, ge=-50, le=300)
    instrument: str | None = None
    reference_electrode: str | None = None
    procedure: str | None = None
    notes: str | None = None
    status: ExperimentStatus | None = None


class ExperimentOut(Orm, ExperimentBase):
    id: int
    code: str
    specimen_id: int
    is_demo: bool
    created_at: datetime
    updated_at: datetime


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int


# ---------------- wettability ----------------

class CAParams(BaseModel):
    mode: Literal["auto", "manual_tangent"] = "auto"
    roi: list[int] | None = Field(None, min_length=4, max_length=4)
    baseline: list[Point] | None = Field(None, min_length=2, max_length=2)
    contact_left: Point | None = Field(None, min_length=2, max_length=2)
    contact_right: Point | None = Field(None, min_length=2, max_length=2)
    tangent_left: Point | None = Field(None, min_length=2, max_length=2)
    tangent_right: Point | None = Field(None, min_length=2, max_length=2)
    threshold: float | None = Field(None, ge=0, le=255)
    polarity: Literal["auto", "dark_drop", "light_drop"] = "auto"
    fit_radius_px: float | None = Field(None, gt=0, le=5000)
    primary_method: Literal["polynomial", "circle"] | None = None


class CAMeasurementMeta(BaseModel):
    specimen_id: int
    experiment_id: int | None = None
    liquid: str = Field("Deionised water", min_length=1, max_length=80)
    droplet_volume_ul: float | None = Field(None, gt=0, le=1000)
    captured_at: datetime | None = None
    notes: str | None = Field(None, max_length=5000)
    status: Literal["accepted", "rejected"] = "accepted"
    rejection_reason: str | None = Field(None, max_length=2000)


class CAPatch(BaseModel):
    notes: str | None = None
    experiment_id: int | None = None
    liquid: str | None = Field(None, min_length=1, max_length=80)
    droplet_volume_ul: float | None = Field(None, gt=0, le=1000)
    status: Literal["accepted", "rejected"] | None = None
    rejection_reason: str | None = None
    reanalyse_params: CAParams | None = None
    reason: str | None = Field(None, max_length=2000)


class CARunOut(Orm):
    id: int
    specimen_id: int
    experiment_id: int | None
    image_artifact_id: int
    overlay_artifact_id: int | None
    method: str
    status: str
    left_deg: float | None
    right_deg: float | None
    mean_deg: float | None
    classification: str | None
    analysis_params: dict
    diagnostics: dict
    warnings: list
    auto_result: dict | None
    algorithm_version: str
    liquid: str
    droplet_volume_ul: float | None
    captured_at: datetime | None
    measured_at: datetime
    rejection_reason: str | None
    notes: str | None
    is_demo: bool
    created_at: datetime


# ---------------- corrosion ----------------

class ImportMeta(BaseModel):
    method: Literal["ocp", "lpr", "pdp", "eis"]
    mapping: dict[str, str]
    units: dict[str, str | None]
    imag_convention: Literal["as_is", "negated"] = "as_is"
    anodic_negative: bool = False
    specimen_id: int
    experiment_id: int | None = None
    exposed_area_cm2: float | None = Field(None, gt=0, le=10000)
    area_source: str | None = Field(None, max_length=200)
    reference_electrode: str | None = Field(None, max_length=120)
    instrument: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=5000)


class MaterialIn(BaseModel):
    profile: str | None = None
    equivalent_weight_g_eq: float | None = Field(None, gt=0, le=500)
    density_g_cm3: float | None = Field(None, gt=0, le=30)
    source: str | None = Field(None, max_length=500)
    is_alloy: bool = False


class AnalyzeRequest(BaseModel):
    params: dict[str, Any] = {}
    material: MaterialIn | None = None


class CorrosionRunOut(Orm):
    id: int
    specimen_id: int
    experiment_id: int | None
    raw_artifact_id: int
    processed_artifact_id: int
    method: str
    column_mapping: dict
    units: dict
    import_meta: dict
    parser_warnings: list
    exposed_area_cm2: float | None
    area_source: str | None
    reference_electrode: str | None
    instrument: str | None
    n_points: int
    analysis_status: str
    notes: str | None
    is_demo: bool
    created_at: datetime


class MetricOut(Orm):
    id: int
    corrosion_run_id: int
    analysis_id: int
    name: str
    label: str
    value: float | None
    unit: str
    origin: str
    formula: str
    method_version: str
    parameters: dict
    assumptions: list
    warnings: list
    valid: bool
    superseded: bool
    created_at: datetime


# ---------------- ML ----------------

class DatasetRequest(BaseModel):
    target: str = "i_corr"
    baseline_features: list[str] = ["material", "surface_preparation", "electrolyte", "temperature_c"]
    data_source: Literal["real", "demo"] = "real"
    target_transform: Literal["none", "log10"] = "log10"


class TrainRequest(DatasetRequest):
    seed: int | None = None


class PredictRequest(BaseModel):
    run_id: int
    inputs: dict[str, Any]


class SettingsIn(BaseModel):
    analysis: dict[str, dict[str, Any]]
