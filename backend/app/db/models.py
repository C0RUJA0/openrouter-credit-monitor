"""SQLAlchemy ORM models: settings, monitor_state, events."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import DecimalString


def utcnow() -> datetime:
    # Naive UTC to stay consistent with SQLite DateTime columns (no tz stored).
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_threshold: Mapped[Decimal] = mapped_column(DecimalString, nullable=False)
    check_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class MonitorState(Base):
    __tablename__ = "monitor_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_balance: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    last_total_credits: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    last_total_usage: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    openrouter_status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    evolution_status: Mapped[str] = mapped_column(String(16), default="UNKNOWN")
    alert_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_alert_balance: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    # Anti-spam backoff bookkeeping for failed WhatsApp sends.
    alert_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    balance: Mapped[Decimal | None] = mapped_column(DecimalString, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
