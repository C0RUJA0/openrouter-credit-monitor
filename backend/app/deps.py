"""Shared FastAPI dependencies: templates, DB session, auth guard, CSRF."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.runtime import get_runtime
from app.security import csrf_matches, new_csrf_token

_templates: Jinja2Templates | None = None


class AuthRedirect(Exception):
    """Raised to signal the caller should redirect to the login page."""


def get_templates() -> Jinja2Templates:
    global _templates
    if _templates is None:
        _templates = Jinja2Templates(directory=get_runtime().config.templates_dir)
    return _templates


def reset_templates_cache() -> None:
    global _templates
    _templates = None


def db_session():
    """FastAPI dependency yielding a short-lived SQLAlchemy session."""
    session = get_runtime().session_factory()
    try:
        yield session
    finally:
        session.close()


def is_authenticated(request: Request) -> bool:
    cfg = get_runtime().config
    if not cfg.auth_enabled:
        return True
    return bool(request.session.get("user"))


def get_or_create_csrf(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = new_csrf_token()
        request.session["csrf"] = token
    return token


def validate_csrf(request: Request, submitted: str | None) -> bool:
    return csrf_matches(request.session.get("csrf"), submitted)


def login_redirect(request: Request) -> RedirectResponse:
    url = request.url_for("login_page")
    return RedirectResponse(url=str(url), status_code=303)
