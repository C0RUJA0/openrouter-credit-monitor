"""Shared test fixtures: an isolated SQLite DB seeded with defaults."""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings as AppSettings
from app.db.migrations import create_schema, seed_defaults
from app.db.models import Base


@pytest.fixture
def app_settings() -> AppSettings:
    cfg = AppSettings()
    cfg.openrouter_management_key = "test-key"
    cfg.openrouter_base_url = "https://openrouter.test"
    cfg.evolution_api_url = "http://evolution.test"
    cfg.evolution_api_key = "evo-key"
    cfg.evolution_instance = "test-instance"
    cfg.whatsapp_destination = "5511999990000"
    return cfg


@pytest.fixture
def session_factory(tmp_path, app_settings):
    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    create_schema(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    seed_session = SessionLocal()
    try:
        seed_defaults(seed_session, app_settings)
    finally:
        seed_session.close()

    yield SessionLocal
    engine.dispose()


@pytest.fixture
def default_threshold() -> Decimal:
    return Decimal("10.00")
