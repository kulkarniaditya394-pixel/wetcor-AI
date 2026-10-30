"""WETCOR AI backend entry point. Run: uvicorn app.main:app --host 127.0.0.1 --port 8100"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import corrosion, demo, ml, records, reports, system, wettability
from app.core.config import APP_NAME, APP_VERSION, settings
from app.database.session import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("wetcor")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    version = init_db()
    log.info("%s %s ready; schema v%s; data dir %s", APP_NAME, APP_VERSION, version, settings.data_dir)
    yield


app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION, lifespan=lifespan,
              description="Local-first wettability and corrosion intelligence platform. All data stays on this machine.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"], allow_headers=["*"], expose_headers=["Content-Disposition", "X-Content-SHA256"])


@app.exception_handler(RequestValidationError)
async def validation_handler(_req: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]})


@app.exception_handler(Exception)
async def unhandled(_req: Request, exc: Exception):
    log.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal error. See the backend log window for details."})


for r in (system, records, wettability, corrosion, ml, reports, demo):
    app.include_router(r.router)
