"""Application entrypoint and wiring (spec sections 12, 13, 27).

Single process / single worker owns the embedded scheduler. The app is built to
run behind a reverse proxy under ROOT_PATH (e.g. /apps/openrouter-monitor), so
all URLs are generated via url_for / root_path and never hardcoded to "/".
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from app.api import actions, auth, dashboard, health
from app.api import settings as settings_api
from app.config import get_settings
from app.db import repository as repo
from app.db.database import get_session, init_engine
from app.db.migrations import create_schema, seed_defaults
from app.events import EventType
from app.runtime import Runtime, clear_runtime, set_runtime
from app.scheduler.jobs import MonitorScheduler
from app.services.monitor import MonitorService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("app")


def _startup(app: FastAPI) -> Runtime:
    cfg = get_settings()

    # 0. refuse to start with insecure auth/session config in production.
    cfg.validate_runtime()

    # 1. validate configuration (presence only, never print secrets).
    if not cfg.openrouter_management_key:
        logger.warning("OPENROUTER_MANAGEMENT_KEY not set; checks will report UNKNOWN")

    # 2. init + migrate SQLite, 3. ensure defaults.
    engine = init_engine(cfg.database_url)
    create_schema(engine)
    seed_session = get_session()
    try:
        seed_defaults(seed_session, cfg)
    finally:
        seed_session.close()

    # 4. build monitor + scheduler.
    monitor = MonitorService(cfg, get_session)
    scheduler = MonitorScheduler(cfg, monitor, get_session)
    runtime = Runtime(config=cfg, session_factory=get_session, monitor=monitor, scheduler=scheduler)
    set_runtime(runtime)

    # record MONITOR_STARTED
    s = get_session()
    try:
        repo.add_event(s, EventType.MONITOR_STARTED, message="monitor started")
        s.commit()
    finally:
        s.close()

    # 6. initial check (safe); 7. never auto-send a test message.
    try:
        monitor.check_balance()
    except Exception:  # noqa: BLE001 - initial check must never block startup
        logger.exception("initial balance check failed")

    # 5. start scheduler last so it doesn't race the initial check.
    scheduler.start()
    return runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = _startup(app)
    try:
        yield
    finally:
        if runtime.scheduler is not None:
            runtime.scheduler.shutdown()
        clear_runtime()


def create_app() -> FastAPI:
    cfg = get_settings()
    app = FastAPI(
        title=cfg.app_title,
        root_path=cfg.root_path,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret,
        same_site="lax",
        https_only=cfg.cookie_secure,
        session_cookie="orcm_session",
    )

    # Optional LAN-only guard (added last so it runs first on each request).
    if cfg.lan_only:
        from app.netguard import LanOnlyMiddleware

        app.add_middleware(LanOnlyMiddleware)
        logger.info("LAN-only access guard enabled")

    app.mount("/static", StaticFiles(directory=cfg.static_dir), name="static")

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(settings_api.router)
    app.include_router(actions.router)
    return app


app = create_app()
