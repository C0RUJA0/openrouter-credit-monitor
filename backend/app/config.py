"""Application configuration loaded from environment variables.

Secrets are read here and never persisted to SQLite, shown in the UI, or logged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

# Project root = parent of the `backend/` directory that holds this package.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent
_FRONTEND_DIR = _PROJECT_ROOT / "frontend"


def _load_env_file(path: Path) -> None:
    """Minimal .env loader (no external dependency).

    Only sets keys that are not already present in the environment, so real
    environment / Docker `env_file` injection always wins over on-disk files.
    """
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bootstrap_env() -> None:
    # backend first (secrets / core), then frontend (UI / proxy-facing).
    _load_env_file(_BACKEND_DIR / ".env")
    _load_env_file(_FRONTEND_DIR / ".env")


_bootstrap_env()


def _get(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is not None:
        value = value.strip()
    return value or default


@dataclass
class Settings:
    # Application
    app_env: str = field(default_factory=lambda: _get("APP_ENV", "production"))
    app_host: str = field(default_factory=lambda: _get("APP_HOST", "0.0.0.0"))
    app_port: int = field(default_factory=lambda: int(_get("APP_PORT", "8080")))
    # root_path for reverse-proxy / Central path prefix. Empty means mounted at "/".
    root_path: str = field(default_factory=lambda: _get("ROOT_PATH", "") or "")

    # Frontend (server-rendered Jinja2) location and presentation vars.
    app_title: str = field(
        default_factory=lambda: _get("APP_TITLE", "OpenRouter Credit Monitor")
    )
    frontend_dir: str = field(
        default_factory=lambda: _get("FRONTEND_DIR", str(_FRONTEND_DIR))
    )

    @property
    def templates_dir(self) -> str:
        return str(Path(self.frontend_dir) / "templates")

    @property
    def static_dir(self) -> str:
        return str(Path(self.frontend_dir) / "static")

    # OpenRouter
    openrouter_management_key: str | None = field(
        default_factory=lambda: _get("OPENROUTER_MANAGEMENT_KEY")
    )
    openrouter_base_url: str = field(
        default_factory=lambda: _get("OPENROUTER_BASE_URL", "https://openrouter.ai")
    )

    # Evolution API
    evolution_api_url: str | None = field(default_factory=lambda: _get("EVOLUTION_API_URL"))
    evolution_api_key: str | None = field(default_factory=lambda: _get("EVOLUTION_API_KEY"))
    evolution_instance: str | None = field(default_factory=lambda: _get("EVOLUTION_INSTANCE"))
    whatsapp_destination: str | None = field(default_factory=lambda: _get("WHATSAPP_DESTINATION"))

    # Admin auth
    admin_username: str | None = field(default_factory=lambda: _get("ADMIN_USERNAME", "admin"))
    admin_password_hash: str | None = field(default_factory=lambda: _get("ADMIN_PASSWORD_HASH"))
    auth_enabled: bool = field(
        default_factory=lambda: _get("AUTH_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    )
    session_secret: str = field(
        default_factory=lambda: _get("SESSION_SECRET", "change-me-in-production")
    )
    cookie_secure: bool = field(
        default_factory=lambda: _get("COOKIE_SECURE", "false").lower()
        in ("1", "true", "yes", "on")
    )
    # Restrict access to LAN/private clients only (loopback + RFC1918 + link-local).
    lan_only: bool = field(
        default_factory=lambda: _get("LAN_ONLY", "false").lower()
        in ("1", "true", "yes", "on")
    )

    # Database
    database_url: str = field(
        default_factory=lambda: _get("DATABASE_URL", "sqlite:////app/data/monitor.db")
    )

    # Defaults persisted to SQLite on first start (NOT the live values).
    default_threshold: Decimal = field(default_factory=lambda: Decimal("10.00"))
    default_check_interval_seconds: int = 300
    min_check_interval_seconds: int = 60

    # External HTTP timeouts (seconds)
    http_connect_timeout: float = 5.0
    http_read_timeout: float = 10.0

    # Event retention
    event_retention_days: int = 30

    def require_openrouter(self) -> None:
        """Validate required OpenRouter credential exists without printing it."""
        if not self.openrouter_management_key:
            raise RuntimeError(
                "OPENROUTER_MANAGEMENT_KEY is not set. "
                "Set it in the environment before starting the app."
            )

    @property
    def is_production(self) -> bool:
        return (self.app_env or "").strip().lower() == "production"

    def validate_runtime(self) -> None:
        """Fail fast on insecure auth/session config in production.

        Development (APP_ENV != production) stays permissive for local
        convenience. No secret value is ever included in the error messages.
        """
        if not self.is_production:
            return

        errors: list[str] = []

        if not self.auth_enabled:
            errors.append(
                "AUTH_ENABLED must be true in production (refusing to serve "
                "an unauthenticated admin UI)."
            )

        weak_secrets = {"", "change-me-in-production"}
        if (self.session_secret or "") in weak_secrets or len(self.session_secret or "") < 32:
            errors.append(
                "SESSION_SECRET must be a strong random value (>=32 chars) in "
                "production. Generate one with: python -m app.cli gen-secret"
            )

        if not _is_valid_password_hash(self.admin_password_hash):
            errors.append(
                "ADMIN_PASSWORD_HASH must be a valid pbkdf2_sha256 hash in "
                "production. Generate it with: python -m app.cli hash-password '<pw>'"
            )

        if errors:
            raise RuntimeError(
                "Insecure production configuration:\n  - " + "\n  - ".join(errors)
            )

    @property
    def http_timeout(self):
        import httpx

        return httpx.Timeout(
            connect=self.http_connect_timeout,
            read=self.http_read_timeout,
            write=self.http_read_timeout,
            pool=self.http_connect_timeout,
        )


def _is_valid_password_hash(stored: str | None) -> bool:
    """True if `stored` looks like a pbkdf2_sha256$iters$salt$hash value."""
    if not stored:
        return False
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        int(parts[1])
        bytes.fromhex(parts[2])
        bytes.fromhex(parts[3])
    except ValueError:
        return False
    return True


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_cache() -> None:
    """Testing helper: force re-read of environment."""
    global _settings
    _settings = None
