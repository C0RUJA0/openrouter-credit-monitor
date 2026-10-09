"""Schema creation and default seeding.

Deliberately simple: create_all + idempotent seed of the singleton rows. Good
enough for a single-file SQLite DB; no Alembic needed for this scope.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import Settings as AppSettings
from app.db.models import Base, MonitorState, Settings

# Columns added after the initial release. Kept here as lightweight additive
# migrations (ADD COLUMN only) so existing SQLite files upgrade in place without
# Alembic. Never drop/rename — that would risk data loss.
_ADDED_COLUMNS = {
    "settings": {
        "openrouter_key": "VARCHAR(256)",
    },
}


def _apply_additive_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    for table, columns in _ADDED_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        existing = {c["name"] for c in inspector.get_columns(table)}
        with engine.begin() as conn:
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def create_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    _apply_additive_migrations(engine)


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
