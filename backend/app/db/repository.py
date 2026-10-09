"""Thin data-access helpers over the ORM models.

A repository keeps SQL/session details out of the service layer and makes the
singleton `settings`/`monitor_state` rows (id=1) easy to fetch.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Event, MonitorState, Settings, utcnow
from app.events import EventType


def get_settings(session: Session) -> Settings:
    settings = session.get(Settings, 1)
    if settings is None:
        raise RuntimeError("settings row missing; run migrations/seed first")
    return settings


def get_state(session: Session) -> MonitorState:
    state = session.get(MonitorState, 1)
    if state is None:
        raise RuntimeError("monitor_state row missing; run migrations/seed first")
    return state


def add_event(
    session: Session,
    event_type: str,
    *,
    balance: Decimal | None = None,
    message: str | None = None,
    metadata: dict | None = None,
) -> Event:
    event = Event(
        event_type=event_type,
        balance=balance,
        message=message,
        metadata_json=json.dumps(metadata) if metadata else None,
    )
    session.add(event)
    return event


def recent_events(session: Session, limit: int = 20) -> list[Event]:
    stmt = select(Event).order_by(Event.timestamp.desc(), Event.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def prune_events(session: Session, retention_days: int) -> int:
    """Delete events older than retention_days. Returns number deleted."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=retention_days)
    result = session.execute(delete(Event).where(Event.timestamp < cutoff))
    return result.rowcount or 0
