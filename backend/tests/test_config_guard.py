"""Production safety guard: refuse to start with insecure auth/session config
when APP_ENV=production. Dev (APP_ENV!=production) stays permissive."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.security import hash_password

_GOOD_SECRET = "x" * 48
_GOOD_HASH = hash_password("strong-pass")


def _cfg(**over) -> Settings:
    cfg = Settings()
    cfg.app_env = over.get("app_env", "production")
    cfg.auth_enabled = over.get("auth_enabled", True)
    cfg.session_secret = over.get("session_secret", _GOOD_SECRET)
    cfg.admin_username = over.get("admin_username", "admin")
    cfg.admin_password_hash = over.get("admin_password_hash", _GOOD_HASH)
    return cfg


def test_production_valid_config_passes():
    _cfg().validate_runtime()  # must not raise


def test_production_rejects_disabled_auth():
    with pytest.raises(RuntimeError, match="AUTH_ENABLED"):
        _cfg(auth_enabled=False).validate_runtime()


def test_production_rejects_default_session_secret():
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        _cfg(session_secret="change-me-in-production").validate_runtime()


def test_production_rejects_short_session_secret():
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        _cfg(session_secret="short").validate_runtime()


def test_production_rejects_missing_admin_hash():
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_HASH"):
        _cfg(admin_password_hash=None).validate_runtime()


def test_production_rejects_malformed_admin_hash():
    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_HASH"):
        _cfg(admin_password_hash="not-a-valid-hash").validate_runtime()


def test_development_allows_insecure_config():
    # APP_ENV != production -> permissive (local dev convenience).
    _cfg(app_env="development", auth_enabled=False,
         session_secret="change-me-in-production",
         admin_password_hash=None).validate_runtime()
