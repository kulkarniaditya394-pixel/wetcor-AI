"""SQLAlchemy ORM models. See docs/DATA_DICTIONARY.md for field meanings and units."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Specimen(TimestampMixin, Base):
    __tablename__ = "specimens"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    material: Mapped[str] = mapped_column(String(120), index=True)
    batch_source: Mapped[str | None] = mapped_column(String(200))
    dimensions: Mapped[str | None] = mapped_column(String(200))
    surface_preparation: Mapped[str | None] = mapped_column(String(200))
    roughness_ra_um: Mapped[float | None] = mapped_column(Float)
    exposed_area_cm2: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    experiments: Mapped[list[Experiment]] = relationship(back_populates="specimen")


class Experiment(TimestampMixin, Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"), index=True)
    experiment_type: Mapped[str] = mapped_column(String(40))
    performed_at: Mapped[datetime | None] = mapped_column(DateTime)
    operator: Mapped[str | None] = mapped_column(String(120))
    electrolyte: Mapped[str | None] = mapped_column(String(120))
    concentration_value: Mapped[float | None] = mapped_column(Float)
    concentration_unit: Mapped[str | None] = mapped_column(String(20))
    temperature_c: Mapped[float | None] = mapped_column(Float)
    instrument: Mapped[str | None] = mapped_column(String(200))
    reference_electrode: Mapped[str | None] = mapped_column(String(120))
    procedure: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="in_progress")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    specimen: Mapped[Specimen] = relationship(back_populates="experiments")


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)  # raw_image | overlay_image | raw_data | processed_data | report | model
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))  # relative to data_dir
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(100))
    specimen_id: Mapped[int | None] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"), index=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ContactAngleRun(TimestampMixin, Base):
    __tablename__ = "contact_angle_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"), index=True)
    image_artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    overlay_artifact_id: Mapped[int | None] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    method: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="accepted")  # accepted | rejected
    left_deg: Mapped[float | None] = mapped_column(Float)
    right_deg: Mapped[float | None] = mapped_column(Float)
    mean_deg: Mapped[float | None] = mapped_column(Float)
    classification: Mapped[str | None] = mapped_column(String(40))
    analysis_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    auto_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)  # original automatic result, never overwritten
    algorithm_version: Mapped[str] = mapped_column(String(20))
    liquid: Mapped[str] = mapped_column(String(80), default="Deionised water")
    droplet_volume_ul: Mapped[float | None] = mapped_column(Float)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class CorrosionRun(TimestampMixin, Base):
    __tablename__ = "corrosion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    specimen_id: Mapped[int] = mapped_column(ForeignKey("specimens.id", ondelete="RESTRICT"), index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="RESTRICT"), index=True)
    raw_artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    processed_artifact_id: Mapped[int] = mapped_column(ForeignKey("artifacts.id", ondelete="RESTRICT"))
    method: Mapped[str] = mapped_column(String(10), index=True)  # ocp | lpr | pdp | eis
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSON)
    units: Mapped[dict[str, Any]] = mapped_column(JSON)
    import_meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    parser_warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    exposed_area_cm2: Mapped[float | None] = mapped_column(Float)
    area_source: Mapped[str | None] = mapped_column(String(200))
    reference_electrode: Mapped[str | None] = mapped_column(String(120))
    instrument: Mapped[str | None] = mapped_column(String(200))
    n_points: Mapped[int] = mapped_column(Integer)
    analysis_status: Mapped[str] = mapped_column(String(30), default="imported")
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class CorrosionAnalysis(Base):
    """One execution of an analysis with its parameters. Never edited; a re-analysis supersedes it."""
    __tablename__ = "corrosion_analyses"
    id: Mapped[int] = mapped_column(primary_key=True)
    corrosion_run_id: Mapped[int] = mapped_column(ForeignKey("corrosion_runs.id", ondelete="RESTRICT"), index=True)
    method: Mapped[str] = mapped_column(String(10))
    method_version: Mapped[str] = mapped_column(String(20))
    params: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30))  # ok | limited | invalid
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DerivedMetric(Base):
    __tablename__ = "derived_metrics"
    __table_args__ = (Index("ix_metric_run_name", "corrosion_run_id", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    corrosion_run_id: Mapped[int] = mapped_column(ForeignKey("corrosion_runs.id", ondelete="RESTRICT"))
    analysis_id: Mapped[int] = mapped_column(ForeignKey("corrosion_analyses.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(30))
    origin: Mapped[str] = mapped_column(String(20), default="calculated")
    formula: Mapped[str] = mapped_column(Text)
    method_version: Mapped[str] = mapped_column(String(20))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assumptions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MLRun(Base):
    __tablename__ = "ml_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(120))
    model_family: Mapped[str] = mapped_column(String(40))
    feature_set: Mapped[str] = mapped_column(String(20))  # none | baseline | wettability
    features: Mapped[list[Any]] = mapped_column(JSON)
    target: Mapped[str] = mapped_column(String(60))
    target_unit: Mapped[str] = mapped_column(String(30))
    target_transform: Mapped[str] = mapped_column(String(20), default="none")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dataset_hash: Mapped[str] = mapped_column(String(64))
    n_records: Mapped[int] = mapped_column(Integer)
    n_groups: Mapped[int] = mapped_column(Integer)
    split_strategy: Mapped[str] = mapped_column(String(60))
    n_splits: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    oof_predictions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    feature_domain: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    readiness_level: Mapped[str] = mapped_column(String(20))
    includes_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    model_path: Mapped[str | None] = mapped_column(String(500))
    model_sha256: Mapped[str | None] = mapped_column(String(64))
    software_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(String(300))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
