"""Action endpoints: manual check and WhatsApp test (spec sections 10, 24)."""
from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from app.deps import is_authenticated, validate_csrf
from app.runtime import get_runtime
from app.services.evolution import EvolutionError

router = APIRouter()


def _svg_note(text: str) -> Response:
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='220' height='220'>"
        "<rect width='100%' height='100%' fill='#192340' rx='12'/>"
        f"<text x='50%' y='50%' fill='#8A97B4' font-family='sans-serif' "
        f"font-size='13' text-anchor='middle'>{text}</text></svg>"
    )
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@router.get("/actions/whatsapp/qr", name="whatsapp_qr")
async def whatsapp_qr(request: Request):
    """Return the WhatsApp pairing QR as an image. Generated live from Evolution
    (instance is created on demand). Shown in the dashboard until paired."""
    if not is_authenticated(request):
        return RedirectResponse(url=str(request.url_for("login_page")), status_code=303)
    rt = get_runtime()
    try:
        data_uri = await run_in_threadpool(rt.monitor.whatsapp_qr)
    except EvolutionError:
        return _svg_note("Evolution indisponível")
    if not data_uri:
        return _svg_note("Já conectado")
    b64 = data_uri.split(",", 1)[1] if "," in data_uri else data_uri
    try:
        png = base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return _svg_note("QR inválido")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@router.get("/actions/whatsapp/groups", name="whatsapp_groups")
async def whatsapp_groups(request: Request):
    """Return the current WhatsApp groups as JSON for the destination selector.
    Lets the UI refresh the group list without a full page reload."""
    if not is_authenticated(request):
        return JSONResponse([], status_code=401)
    rt = get_runtime()
    groups = await run_in_threadpool(rt.monitor.list_whatsapp_groups)
    return JSONResponse(groups, headers={"Cache-Control": "no-store"})


def _guard(request: Request, csrf_token: str) -> RedirectResponse | None:
    if not is_authenticated(request):
        return RedirectResponse(url=str(request.url_for("login_page")), status_code=303)
    if not validate_csrf(request, csrf_token):
        request.session["flash"] = {"kind": "error", "text": "Sessão inválida. Tente novamente."}
        return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)
    return None


@router.post("/actions/check-now", name="check_now")
async def check_now(request: Request, csrf_token: str = Form("")):
    redirect = _guard(request, csrf_token)
    if redirect is not None:
        return redirect

    rt = get_runtime()
    result = await run_in_threadpool(rt.monitor.check_balance)
    if not result.ran:
        request.session["flash"] = {"kind": "info", "text": "Verificação já em andamento."}
    else:
        request.session["flash"] = {"kind": "ok", "text": "Verificação executada."}
    return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)


@router.post("/actions/test-whatsapp", name="test_whatsapp")
async def test_whatsapp(request: Request, csrf_token: str = Form("")):
    redirect = _guard(request, csrf_token)
    if redirect is not None:
        return redirect

    rt = get_runtime()
    try:
        await run_in_threadpool(rt.monitor.send_test_message)
        request.session["flash"] = {"kind": "ok", "text": "Mensagem de teste enviada."}
    except EvolutionError:
        request.session["flash"] = {
            "kind": "error",
            "text": "Falha ao enviar mensagem de teste. Verifique a Evolution API.",
        }
    return RedirectResponse(url=str(request.url_for("dashboard_page")), status_code=303)
