"""Main dashboard page (spec section 11)."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import db_session, get_or_create_csrf, get_templates, is_authenticated
from app.runtime import get_runtime
from app.web_view import build_dashboard_context

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="dashboard_page")
def dashboard_page(request: Request):
    if not is_authenticated(request):
        return RedirectResponse(url=str(request.url_for("login_page")), status_code=303)

    csrf = get_or_create_csrf(request)
    rt = get_runtime()
    session = rt.session_factory()
    try:
        context = build_dashboard_context(session, rt.config, csrf)
    finally:
        session.close()

    # Groups for the destination selector (best-effort; only when connected).
    groups = []
    if context.get("evolution_connected"):
        try:
            groups = rt.monitor.list_whatsapp_groups()
        except Exception:  # noqa: BLE001 - selector is optional, never fatal
            groups = []
    context["whatsapp_groups"] = groups

    # Surface a one-shot flash message if present.
    context["flash"] = request.session.pop("flash", None)
    return get_templates().TemplateResponse(request, "dashboard.html", context)
