"""Evolution API adapter — the only place that knows Evolution's wire format.

Defaults target Evolution API v2:
  - send text:        POST {base}/message/sendText/{instance}
                      header: apikey: <key>
                      body:   {"number": "<dest>", "text": "<msg>"}
  - instance state:   GET  {base}/instance/connectionState/{instance}
                      -> {"instance": {"state": "open"}}  ("open" == connected)

If the installed Evolution version differs, change ONLY this module. Confirm the
endpoints/body/auth header against the running version before relying on it
(spec section 8.3).
"""
from __future__ import annotations

import httpx

from app.events import EvolutionStatus


class EvolutionError(Exception):
    """Any failure talking to Evolution API."""


class EvolutionClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        instance: str,
        *,
        timeout: httpx.Timeout | float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._key = api_key
        self._instance = instance
        self._timeout = timeout
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
            headers={"apikey": self._key, "Content-Type": "application/json"},
        )

    def send_text(self, destination: str, text: str) -> None:
        """Send a text message. Raises EvolutionError on any failure."""
        path = f"/message/sendText/{self._instance}"
        body = {"number": destination, "text": text}
        try:
            with self._client() as client:
                response = client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise EvolutionError(f"request failed: {type(exc).__name__}") from exc

        if response.status_code not in (200, 201):
            raise EvolutionError(f"unexpected HTTP status {response.status_code}")

    def create_instance(self) -> None:
        """Create the WhatsApp instance (idempotent). Safe to call repeatedly:
        an 'already exists' response is treated as success."""
        body = {
            "instanceName": self._instance,
            "integration": "WHATSAPP-BAILEYS",
            "qrcode": True,
        }
        try:
            with self._client() as client:
                response = client.post("/instance/create", json=body)
        except httpx.HTTPError as exc:
            raise EvolutionError(f"request failed: {type(exc).__name__}") from exc
        # 200/201 created; 403/409 usually means it already exists — not fatal.
        if response.status_code not in (200, 201, 403, 409):
            raise EvolutionError(f"unexpected HTTP status {response.status_code}")

    def get_qr_base64(self) -> str | None:
        """Return the pairing QR as a base64 PNG data URI, or None if already
        connected / no QR available. Connect endpoint returns the current QR."""
        path = f"/instance/connect/{self._instance}"
        try:
            with self._client() as client:
                response = client.get(path)
        except httpx.HTTPError as exc:
            raise EvolutionError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code not in (200, 201):
            raise EvolutionError(f"unexpected HTTP status {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EvolutionError("invalid JSON response") from exc
        if not isinstance(payload, dict):
            return None
        # Evolution v2 may return {"base64": "..."} or nest it under "qrcode".
        b64 = payload.get("base64")
        if not b64 and isinstance(payload.get("qrcode"), dict):
            b64 = payload["qrcode"].get("base64")
        return b64 or None

    def fetch_groups(self) -> list[dict]:
        """List WhatsApp groups as [{'id': '<jid>', 'name': '<subject>'}].

        Requires a connected instance. Raises EvolutionError on failure.
        """
        path = f"/group/fetchAllGroups/{self._instance}?getParticipants=false"
        try:
            with self._client() as client:
                response = client.get(path)
        except httpx.HTTPError as exc:
            raise EvolutionError(f"request failed: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise EvolutionError(f"unexpected HTTP status {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise EvolutionError("invalid JSON response") from exc
        groups = payload if isinstance(payload, list) else payload.get("groups", [])
        out: list[dict] = []
        for g in groups or []:
            if not isinstance(g, dict):
                continue
            gid = g.get("id")
            if not gid:
                continue
            out.append({"id": gid, "name": g.get("subject") or gid})
        return out

    def get_instance_status(self) -> str:
        """Return an EvolutionStatus value based on the real instance state.

        Never claims CONNECTED just because HTTP 200 came back — it inspects the
        reported connection state (spec section 11).
        """
        path = f"/instance/connectionState/{self._instance}"
        try:
            with self._client() as client:
                response = client.get(path)
        except httpx.HTTPError:
            return EvolutionStatus.ERROR

        if response.status_code != 200:
            return EvolutionStatus.ERROR

        try:
            payload = response.json()
        except ValueError:
            return EvolutionStatus.ERROR

        state = None
        if isinstance(payload, dict):
            inst = payload.get("instance")
            if isinstance(inst, dict):
                state = inst.get("state")
            if state is None:
                state = payload.get("state")

        if state == "open":
            return EvolutionStatus.CONNECTED
        if state in ("close", "closed", "connecting", "disconnected"):
            return EvolutionStatus.DISCONNECTED
        return EvolutionStatus.UNKNOWN
