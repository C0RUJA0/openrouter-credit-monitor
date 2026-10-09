"""UI-editable OpenRouter key override (deviation from the env-only spec).

Security guarantees that MUST hold even with the override:
- the key is never returned in the dashboard context (only a masked hint/bool);
- an empty form field keeps the existing key;
- the DB key takes precedence over the env key when present.
"""
from __future__ import annotations

from decimal import Decimal

from app.db import repository as repo
from app.db.migrations import create_schema, seed_defaults
from app.services.monitor import MonitorService
from app.web_view import build_dashboard_context


def test_settings_row_has_openrouter_key_column(session_factory):
    s = session_factory()
    try:
        row = repo.get_settings(s)
        assert hasattr(row, "openrouter_key")
        assert row.openrouter_key is None  # unset by default
    finally:
        s.close()


def test_effective_key_prefers_db_over_env(app_settings, session_factory):
    app_settings.openrouter_management_key = "env-key"
    m = MonitorService(app_settings, session_factory)
    s = session_factory()
    try:
        row = repo.get_settings(s)
        # no override -> env key
        assert m._effective_openrouter_key(row) == "env-key"
        # override set -> db key wins
        row.openrouter_key = "db-key"
        assert m._effective_openrouter_key(row) == "db-key"
    finally:
        s.close()


def test_dashboard_never_exposes_raw_key(app_settings, session_factory):
    s = session_factory()
    try:
        row = repo.get_settings(s)
        row.openrouter_key = "sk-or-super-secret-value-123456"
        s.commit()
        ctx = build_dashboard_context(s, app_settings, "csrf")
    finally:
        s.close()
    # raw key must not appear anywhere in the context
    assert "sk-or-super-secret-value-123456" not in str(ctx)
    assert ctx["openrouter_key_set"] is True
    # masked hint only shows the tail
    assert ctx["openrouter_key_masked"].endswith("3456")
    assert "super-secret" not in ctx["openrouter_key_masked"]


def test_dashboard_key_unset_reports_false(app_settings, session_factory):
    app_settings.openrouter_management_key = None  # no env key either
    s = session_factory()
    try:
        ctx = build_dashboard_context(s, app_settings, "csrf")
    finally:
        s.close()
    assert ctx["openrouter_key_set"] is False


def test_evolution_override_resolution_and_masking(app_settings, session_factory):
    # env defaults from conftest; override url+key+dest via DB
    s = session_factory()
    try:
        row = repo.get_settings(s)
        row.evolution_api_url = "http://evo.db.local"
        row.evolution_api_key = "evo-db-secret-9999"
        row.evolution_instance = "db-inst"
        row.whatsapp_destination = "5511888887777"
        s.commit()
        ctx = build_dashboard_context(s, app_settings, "csrf")
    finally:
        s.close()
    # raw evolution key never exposed
    assert "evo-db-secret-9999" not in str(ctx)
    assert ctx["evolution_key_set"] is True
    assert ctx["evolution_key_masked"].endswith("9999")
    assert ctx["evolution_key_source"] == "UI"
    assert ctx["evolution_url"] == "http://evo.db.local"
    assert ctx["evolution_instance_value"] == "db-inst"


def test_evolution_client_uses_db_override(app_settings, session_factory):
    m = MonitorService(app_settings, session_factory)
    s = session_factory()
    try:
        row = repo.get_settings(s)
        row.evolution_api_url = "http://evo.db.local"
        row.evolution_api_key = "k"
        row.evolution_instance = "inst"
        s.commit()
        client = m._evolution_client(row)
    finally:
        s.close()
    assert client is not None
    assert client._base_url == "http://evo.db.local"
    assert client._instance == "inst"
