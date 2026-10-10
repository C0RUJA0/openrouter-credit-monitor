"""Builds the sanitized view-model for the dashboard template.

Never exposes secrets: the WhatsApp destination is masked and no API keys are
included anywhere in the context.
"""
from __future__ import annotations

from app.config import Settings as AppSettings
from app.db import repository as repo
from app.events import BalanceStatus, OpenRouterStatus
from app.intervals import split as _split_interval
from app.money import format_usd
from app.services.monitor import parse_destinations as _parse_targets


def _mask_destination(dest: str | None) -> str:
    if not dest:
        return "—"
    tail = dest[-4:]
    return "*" * max(len(dest) - 4, 0) + tail


def _mask_secret(value: str | None) -> str:
    """Show only the last 4 chars; never the full secret."""
    if not value:
        return "—"
    tail = value[-4:]
    return "•" * max(min(len(value) - 4, 8), 0) + tail


def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%d/%m/%Y %H:%M")


def _gauge_pct(balance, threshold) -> int:
    """Balance position on a 0..(2*threshold) meter, so the threshold sits at
    the midpoint (50%). Clamped to 2..100. 0 when unknown."""
    if balance is None or threshold is None or threshold <= 0:
        return 0
    scale = float(threshold) * 2
    pct = float(balance) / scale * 100
    return max(2, min(100, round(pct)))


def _balance_status(state, threshold) -> str:
    if state.last_balance is None:
        return BalanceStatus.UNKNOWN
    if state.openrouter_status == OpenRouterStatus.ERROR and state.last_success_at is None:
        return BalanceStatus.UNKNOWN
    return BalanceStatus.LOW if state.last_balance <= threshold else BalanceStatus.NORMAL


def build_dashboard_context(session, config: AppSettings, csrf_token: str) -> dict:
    settings_row = repo.get_settings(session)
    state = repo.get_state(session)
    events = repo.recent_events(session, limit=20)

    balance_status = _balance_status(state, settings_row.alert_threshold)

    # Effective Evolution config: DB override wins over env, per field.
    eff_url = settings_row.evolution_api_url or config.evolution_api_url
    eff_evo_key = settings_row.evolution_api_key or config.evolution_api_key
    eff_instance = settings_row.evolution_instance or config.evolution_instance
    eff_destination = settings_row.whatsapp_destination or config.whatsapp_destination

    event_rows = [
        {
            "time": e.timestamp.strftime("%d/%m %H:%M"),
            "type": e.event_type,
            "balance": format_usd(e.balance) if e.balance is not None else "—",
            "message": e.message or "",
        }
        for e in events
    ]

    return {
        "app_title": config.app_title,
        "balance_display": format_usd(state.last_balance),
        "balance_status": balance_status,
        "gauge_pct": _gauge_pct(state.last_balance, settings_row.alert_threshold),
        "gauge_threshold_pct": 50,
        "threshold_display": format_usd(settings_row.alert_threshold),
        "threshold_input": f"{settings_row.alert_threshold:.2f}",
        "notifications_enabled": settings_row.notifications_enabled,
        "check_interval_seconds": settings_row.check_interval_seconds,
        "interval_value": _split_interval(settings_row.check_interval_seconds)[0],
        "interval_unit": _split_interval(settings_row.check_interval_seconds)[1],
        "openrouter_status": state.openrouter_status,
        "evolution_status": state.evolution_status,
        "last_check_at": _fmt_dt(state.last_check_at),
        "last_success_at": _fmt_dt(state.last_success_at),
        "last_alert_at": _fmt_dt(state.last_alert_at),
        "whatsapp_instance": eff_instance or "—",
        "whatsapp_destination_masked": _mask_destination(eff_destination),
        # Evolution config (effective = DB override or env), for the UI form.
        "evolution_url": eff_url or "",
        "evolution_instance_value": eff_instance or "",
        "whatsapp_destination_value": eff_destination or "",
        "whatsapp_targets": _parse_targets(eff_destination),
        "evolution_key_set": bool(eff_evo_key),
        "evolution_key_masked": _mask_secret(eff_evo_key),
        "evolution_key_source": "UI" if settings_row.evolution_api_key else "env",
        # Is Evolution wired up (so we can show the QR flow) and is it paired?
        "evolution_available": bool(eff_url and eff_evo_key and eff_instance),
        "evolution_connected": state.evolution_status == "CONNECTED",
        # OpenRouter key: expose only whether it is set and a masked hint.
        # The effective key is the DB override if present, else the env key.
        "openrouter_key_set": bool(settings_row.openrouter_key or config.openrouter_management_key),
        "openrouter_key_masked": _mask_secret(
            settings_row.openrouter_key or config.openrouter_management_key
        ),
        "openrouter_key_source": "UI" if settings_row.openrouter_key else "env",
        "events": event_rows,
        "csrf_token": csrf_token,
    }
