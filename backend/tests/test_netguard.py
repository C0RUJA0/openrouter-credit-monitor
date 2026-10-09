"""LAN-only access guard: when enabled, only private/loopback clients pass."""
from __future__ import annotations

import pytest

from app.netguard import is_lan_address


@pytest.mark.parametrize("host", [
    "127.0.0.1", "::1",
    "192.168.1.50", "10.0.0.5", "172.16.3.9",
    "169.254.1.1",            # link-local
    "fd00::1",                # unique local IPv6
])
def test_private_and_loopback_allowed(host):
    assert is_lan_address(host) is True


@pytest.mark.parametrize("host", [
    "8.8.8.8", "1.1.1.1", "93.184.216.34",
    "2001:4860:4860::8888",   # public IPv6
])
def test_public_blocked(host):
    assert is_lan_address(host) is False


@pytest.mark.parametrize("host", ["", None, "not-an-ip", "testclient"])
def test_unparseable_blocked(host):
    assert is_lan_address(host) is False
