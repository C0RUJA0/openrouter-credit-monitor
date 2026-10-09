"""OpenRouter Credits API adapter.

Isolated so the rest of the app never depends on OpenRouter request details.
Source of truth: GET {base}/api/v1/credits  (spec section 3).

    balance = total_credits - total_usage

A failure here is NEVER interpreted as a zero balance — callers receive an
exception and must preserve the last known balance.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

from app.money import to_decimal

CREDITS_PATH = "/api/v1/credits"


class OpenRouterError(Exception):
    """Any failure talking to OpenRouter (network, HTTP status, bad JSON)."""


@dataclass(frozen=True)
class CreditsResult:
    total_credits: Decimal
    total_usage: Decimal

    @property
    def balance(self) -> Decimal:
        return self.total_credits - self.total_usage


class OpenRouterClient:
    def __init__(
        self,
        base_url: str,
        management_key: str,
        *,
        timeout: httpx.Timeout | float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._key = management_key
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self._key}"},
        )

    def get_credits(self) -> CreditsResult:
        try:
            with self._client() as client:
                response = client.get(CREDITS_PATH)
        except httpx.HTTPError as exc:
            # Do not include exc detail verbatim in anything user-facing; it may
            # carry URLs/headers. Keep the type name only.
            raise OpenRouterError(f"request failed: {type(exc).__name__}") from exc

        if response.status_code != 200:
            raise OpenRouterError(f"unexpected HTTP status {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenRouterError("invalid JSON response") from exc

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise OpenRouterError("unexpected response shape (missing 'data')")

        if "total_credits" not in data or "total_usage" not in data:
            raise OpenRouterError("missing total_credits/total_usage fields")

        try:
            total_credits = to_decimal(data["total_credits"])
            total_usage = to_decimal(data["total_usage"])
        except Exception as exc:  # noqa: BLE001 - normalize to one error type
            raise OpenRouterError("non-numeric credit fields") from exc

        return CreditsResult(total_credits=total_credits, total_usage=total_usage)
