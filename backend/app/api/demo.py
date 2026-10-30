"""Explicit load/reset of the clearly labelled synthetic demo workspace."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_session
from app.services import demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("")
def status(db: Session = Depends(get_session)):
    return demo.demo_status(db)


@router.post("/load")
def load(db: Session = Depends(get_session)):
    try:
        return demo.load_demo(db)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.delete("")
def reset(confirm: str = Query(...), db: Session = Depends(get_session)):
    if confirm != "RESET-DEMO":
        raise HTTPException(400, "Type RESET-DEMO to confirm. Only records flagged as demo are removed.")
    return demo.reset_demo(db, settings.models_dir)
