import httpx
import pytest

from app.events import EvolutionStatus
from app.services.evolution import EvolutionClient, EvolutionError


def _client(handler):
    transport = httpx.MockTransport(handler)
    return EvolutionClient("http://evo.test", "key", "inst", transport=transport)


def test_send_success():
    def handler(request):
        assert request.headers.get("apikey") == "key"
        assert "/message/sendText/inst" in str(request.url)
        return httpx.Response(201, json={"status": "ok"})

    _client(handler).send_text("5511999", "hello")  # no raise


def test_send_http_error_raises():
    def handler(request):
        return httpx.Response(400, json={"error": "bad"})

    with pytest.raises(EvolutionError):
        _client(handler).send_text("x", "y")


def test_send_timeout_raises():
    def handler(request):
        raise httpx.ReadTimeout("t", request=request)

    with pytest.raises(EvolutionError):
        _client(handler).send_text("x", "y")


def test_instance_status_open_is_connected():
    def handler(request):
        return httpx.Response(200, json={"instance": {"state": "open"}})

    assert _client(handler).get_instance_status() == EvolutionStatus.CONNECTED


def test_instance_status_closed_is_disconnected():
    def handler(request):
        return httpx.Response(200, json={"instance": {"state": "close"}})

    assert _client(handler).get_instance_status() == EvolutionStatus.DISCONNECTED


def test_instance_status_http_error_is_error():
    def handler(request):
        return httpx.Response(500)

    assert _client(handler).get_instance_status() == EvolutionStatus.ERROR
