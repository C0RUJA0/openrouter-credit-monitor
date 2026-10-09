"""LAN-only access guard.

When enabled (LAN_ONLY=true), requests are allowed only from loopback,
RFC1918 private, link-local, or unique-local addresses — i.e. the home/LAN
network — and rejected from public IPs.

Note: behind a reverse proxy the peer IP is the proxy's. For true LAN-only
exposure, also avoid routing the app through a public proxy. See docs.
"""
from __future__ import annotations

import ipaddress
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse

logger = logging.getLogger("netguard")


def is_lan_address(host: str | None) -> bool:
    """True if `host` is a loopback/private/link-local address."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


class LanOnlyMiddleware(BaseHTTPMiddleware):
    """Reject non-LAN clients with 403. Enable via LAN_ONLY=true."""

    async def dispatch(self, request: Request, call_next):
        client = request.client
        host = client.host if client else None
        if not is_lan_address(host):
            logger.warning("blocked non-LAN request from %s", host)
            return PlainTextResponse("Forbidden: LAN-only access.", status_code=403)
        return await call_next(request)
