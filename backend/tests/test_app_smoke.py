"""End-to-end smoke test: the app boots (lifespan runs the scheduler + initial
check), serves health/readiness and the dashboard, and shuts down cleanly.

Runs in development mode with auth disabled so no secrets are needed.
"""
from __future__ import annotations

import importlib

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("ROOT_PATH", "")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'smoke.db'}")
    # No OPENROUTER key: initial check degrades to UNKNOWN, must not crash boot.
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_KEY", raising=False)

    import app.config as config
    import app.deps as deps
    import app.db.database as database
    import app.runtime as runtime
    config.reset_settings_cache()
    database.reset_engine()
    deps.reset_templates_cache()
    runtime.clear_runtime()

    import app.main as main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c

    config.reset_settings_cache()
    database.reset_engine()
    deps.reset_templates_cache()
    runtime.clear_runtime()


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_readyz_ready_after_boot(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": True, "schema": True, "scheduler": True}


def test_dashboard_renders_with_auth_disabled(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Saldo atual" in r.text


def test_static_css_served(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200
