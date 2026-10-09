"""Schema creation and default seeding.

Deliberately simple: create_all + idempotent seed of the singleton rows. Good
enough for a single-file SQLite DB; no Alembic needed for this scope.
"""
from __future__ import annotations

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings as AppSettings
from app.db.models import Base, MonitorState, Settings


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def seed_defaults(session: Session, app_settings: AppSettings) -> None:
    """Ensure the singleton settings (id=1) and monitor_state (id=1) rows exist."""
    if session.get(Settings, 1) is None:
        session.add(
            Settings(
                id=1,
                alert_threshold=app_settings.default_threshold,
                check_interval_seconds=app_settings.default_check_interval_seconds,
                notifications_enabled=True,
            )
        )
    if session.get(MonitorState, 1) is None:
        session.add(
            MonitorState(
                id=1,
                openrouter_status="UNKNOWN",
                evolution_status="UNKNOWN",
                alert_triggered=False,
                alert_attempt_count=0,
            )
        )
    session.commit()
