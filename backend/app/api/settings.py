"""Settings form handler (spec section 7). Persists threshold immediately, then
re-evaluates the last known balance once (no spam)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.db import repository as repo
from app.deps import is_authenticated, validate_csrf
from app.events import EventType
from app.money import format_usd, parse_money
from app.runtime import get_runtime

logger = logging.getLogger("api.settings")
router = APIRouter()


@router.post("/settings", name="update_settings")
async def update_settings(
    request: Request,
    alert_threshold: str = Form(...),
    notifications_enabled: str = Form(None),
    check_interval_seconds: str = Form(None),
    openrouter_key: str = Form(None),
    csrf_token: str = Form(""),
):
    if not is_authenticated(request):
        return RedirectResponse(url=str(request.url_for("login_page")), status_code=303)
    if not validate_csrf(request, csrf_token):
        request.session["flash"] = {"kind": "error", "text": "Sessão inválida. Tente novamente."}
        return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)

    rt = get_runtime()
    cfg = rt.config

    try:
        new_threshold = parse_money(alert_threshold)
    except ValueError:
        request.session["flash"] = {"kind": "error", "text": "Valor de limite inválido."}
        return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)

    new_notifications = notifications_enabled is not None

    new_interval = None
    if check_interval_seconds:
        try:
            new_interval = int(check_interval_seconds)
        except ValueError:
            new_interval = None
        if new_interval is not None and new_interval < cfg.min_check_interval_seconds:
            new_interval = cfg.min_check_interval_seconds

    session = rt.session_factory()
    try:
        settings_row = repo.get_settings(session)
        old_threshold = settings_row.alert_threshold
        old_notifications = settings_row.notifications_enabled
        old_interval = settings_row.check_interval_seconds

        settings_row.alert_threshold = new_threshold
        settings_row.notifications_enabled = new_notifications
        if new_interval is not None:
            settings_row.check_interval_seconds = new_interval

        # Optional OpenRouter key override: write-only. A non-empty value
        # replaces the stored key; the literal "-" clears it (fall back to env).
        # The value itself is never logged or echoed back.
        key_changed = False
        if openrouter_key is not None:
            submitted = openrouter_key.strip()
            if submitted == "-":
                settings_row.openrouter_key = None
                key_changed = True
            elif submitted:
                settings_row.openrouter_key = submitted
                key_changed = True

        repo.add_event(
            session,
            EventType.SETTINGS_CHANGED,
            message=f"threshold {format_usd(old_threshold)} -> {format_usd(new_threshold)}",
            metadata={
                "old_threshold": str(old_threshold),
                "new_threshold": str(new_threshold),
                "old_notifications": old_notifications,
                "new_notifications": new_notifications,
                "old_interval": old_interval,
                "new_interval": settings_row.check_interval_seconds,
                "openrouter_key_changed": key_changed,
            },
        )
        session.commit()
    finally:
        session.close()

    # Reschedule if interval changed and scheduler is running.
    if new_interval is not None and new_interval != old_interval and rt.scheduler is not None:
        try:
            rt.scheduler.reschedule(new_interval)
        except Exception:  # noqa: BLE001
            logger.exception("failed to reschedule after interval change")

    # If the key changed, run a real check so the UI reflects the new key's
    # status immediately; otherwise just re-evaluate the last known balance.
    if key_changed:
        await run_in_threadpool(rt.monitor.check_balance)
    else:
        await run_in_threadpool(rt.monitor.reevaluate_now)

    request.session["flash"] = {"kind": "ok", "text": "Configurações salvas."}
    return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)
