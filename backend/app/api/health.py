"""Liveness and readiness endpoints (spec section 17). Unauthenticated.

/healthz must NOT depend on OpenRouter/Evolution/WhatsApp availability — an
external outage does not mean the local process is dead.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db import repository as repo
from app.runtime import get_runtime

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "healthy"}


@router.get("/readyz")
def readyz() -> JSONResponse:
    checks = {"database": False, "schema": False, "scheduler": False}
    rt = get_runtime()
    try:
        session = rt.session_factory()
        try:
            session.execute(text("SELECT 1"))
            checks["database"] = True
            repo.get_settings(session)
            repo.get_state(session)
            checks["schema"] = True
        finally:
            session.close()
    except Exception:  # noqa: BLE001
        pass

    checks["scheduler"] = bool(rt.scheduler and rt.scheduler.running)

    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )
