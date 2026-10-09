from decimal import Decimal

import httpx
import pytest

from app.services.openrouter import OpenRouterClient, OpenRouterError


def _client(handler):
    transport = httpx.MockTransport(handler)
    return OpenRouterClient("https://openrouter.test", "key", transport=transport)


def test_valid_response_computes_balance():
    def handler(request):
        return httpx.Response(200, json={"data": {"total_credits": "50.00", "total_usage": "17.53"}})

    result = _client(handler).get_credits()
    assert result.total_credits == Decimal("50.00")
    assert result.total_usage == Decimal("17.53")
    assert result.balance == Decimal("32.47")


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_errors_raise(status):
    def handler(request):
        return httpx.Response(status, json={"error": "x"})

    with pytest.raises(OpenRouterError):
        _client(handler).get_credits()


def test_timeout_raises():
    def handler(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(OpenRouterError):
        _client(handler).get_credits()


def test_invalid_json_raises():
    def handler(request):
        return httpx.Response(200, content=b"not json", headers={"content-type": "application/json"})

    with pytest.raises(OpenRouterError):
        _client(handler).get_credits()


def test_missing_fields_raise():
    def handler(request):
        return httpx.Response(200, json={"data": {"total_credits": "10.00"}})

    with pytest.raises(OpenRouterError):
        _client(handler).get_credits()


def test_unexpected_shape_raises():
    def handler(request):
        return httpx.Response(200, json={"foo": "bar"})

    with pytest.raises(OpenRouterError):
        _client(handler).get_credits()


def test_authorization_header_sent():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"total_credits": "1", "total_usage": "0"}})

    _client(handler).get_credits()
    assert seen["auth"] == "Bearer key"
