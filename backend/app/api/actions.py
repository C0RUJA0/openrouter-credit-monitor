"""Action endpoints: manual check and WhatsApp test (spec sections 10, 24)."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.deps import is_authenticated, validate_csrf
from app.runtime import get_runtime
from app.services.evolution import EvolutionError

router = APIRouter()


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
