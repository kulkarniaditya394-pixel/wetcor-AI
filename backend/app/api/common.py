"""Helpers shared by API routers."""
from __future__ import annotations

import json
from typing import TypeVar

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core import defaults as D
from app.core.config import settings
from app.database.models import AppSetting, Experiment, Specimen

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


def get_or_404(db: Session, model: type[T], obj_id: int, label: str | None = None) -> T:
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{label or model.__name__} {obj_id} not found")
    return obj


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"File exceeds the {settings.max_upload_bytes // (1024 * 1024)} MB upload limit.")
    if not data:
        raise HTTPException(422, "Uploaded file is empty.")
    return data


def parse_form_json(raw: str | None, model: type[M]) -> M:
    try:
        return model.model_validate(json.loads(raw) if raw else {})
    except json.JSONDecodeError as exc:
        raise HTTPException(422, f"Invalid JSON in form field: {exc.msg}") from None
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from None


def limits(db: Session) -> dict:
    row = db.get(AppSetting, "analysis")
    return D.merge(row.value if row else None)


def check_links(db: Session, specimen_id: int, experiment_id: int | None) -> tuple[Specimen, Experiment | None]:
    spec = get_or_404(db, Specimen, specimen_id, "Specimen")
    exp = None
    if experiment_id is not None:
        exp = get_or_404(db, Experiment, experiment_id, "Experiment")
        if exp.specimen_id != spec.id:
            raise HTTPException(422, f"Experiment {exp.code} belongs to a different specimen.")
    return spec, exp
