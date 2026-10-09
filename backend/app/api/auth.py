"""Admin login/logout. Session cookie carries only a username flag — no secret."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_or_create_csrf, get_templates, validate_csrf
from app.runtime import get_runtime
from app.security import verify_password

router = APIRouter()


@router.get("/login", response_class=HTMLResponse, name="login_page")
def login_page(request: Request):
    cfg = get_runtime().config
    if not cfg.auth_enabled or request.session.get("user"):
        return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)
    csrf = get_or_create_csrf(request)
    return get_templates().TemplateResponse(
        request, "login.html", {"error": None, "csrf_token": csrf, "app_title": cfg.app_title}
    )


@router.post("/login", response_class=HTMLResponse, name="login_submit")
def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    csrf_token: str = Form(""),
):
    cfg = get_runtime().config
    templates = get_templates()

    if not validate_csrf(request, csrf_token):
        csrf = get_or_create_csrf(request)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Sessão inválida. Tente novamente.", "csrf_token": csrf,
             "app_title": cfg.app_title},
            status_code=400,
        )

    ok = (
        username == (cfg.admin_username or "")
        and verify_password(password, cfg.admin_password_hash)
    )
    if not ok:
        csrf = get_or_create_csrf(request)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Usuário ou senha inválidos.", "csrf_token": csrf,
             "app_title": cfg.app_title},
            status_code=401,
        )

    request.session["user"] = username
    return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)


@router.post("/logout", name="logout")
def logout(request: Request):
    request.session.pop("user", None)
    return RedirectResponse(url=str(request.url_for("login_page")), status_code=303)
