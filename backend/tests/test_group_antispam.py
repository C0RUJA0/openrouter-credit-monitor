"""Group anti-spam: skip a group target when the bot is already the last message."""
from __future__ import annotations

from decimal import Decimal

import httpx

from app.db import repository as repo
from app.services.evolution import EvolutionClient
from app.services.monitor import MonitorService
from app.services.openrouter import CreditsResult


def test_adapter_detects_last_from_me():
    def handler(request):
        return httpx.Response(200, json={"messages": {"records": [
            {"key": {"fromMe": False}, "messageTimestamp": 100},
            {"key": {"fromMe": True}, "messageTimestamp": 200},  # latest
        ]}})
    c = EvolutionClient("http://e", "k", "i", transport=httpx.MockTransport(handler))
    assert c.last_message_is_from_me("123@g.us") is True


def test_adapter_detects_last_from_other():
    def handler(request):
        return httpx.Response(200, json=[
            {"key": {"fromMe": True}, "messageTimestamp": 100},
            {"key": {"fromMe": False}, "messageTimestamp": 300},  # latest
        ])
    c = EvolutionClient("http://e", "k", "i", transport=httpx.MockTransport(handler))
    assert c.last_message_is_from_me("123@g.us") is False


def test_adapter_none_on_empty_or_error():
    c = EvolutionClient("http://e", "k", "i",
                        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"messages": {"records": []}})))
    assert c.last_message_is_from_me("123@g.us") is None
    c2 = EvolutionClient("http://e", "k", "i",
                         transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert c2.last_message_is_from_me("123@g.us") is None


class SpyEvo:
    def __init__(self, last_from_me): self.sent = []; self._lfm = last_from_me
    def send_text(self, dest, text): self.sent.append(dest)
    def get_instance_status(self): return "CONNECTED"
    def last_message_is_from_me(self, jid): return self._lfm


def _mk(app_settings, sf, evo):
    class FakeOR:
        def get_credits(self): return CreditsResult(total_credits=Decimal("5"), total_usage=Decimal("0"))
    return MonitorService(app_settings, sf, openrouter_client=FakeOR(), evolution_client=evo)


def _set_dest(sf, value):
    s = sf()
    try:
        repo.get_settings(s).whatsapp_destination = value
        s.commit()
    finally:
        s.close()


def test_group_skipped_when_bot_is_last(app_settings, session_factory):
    evo = SpyEvo(last_from_me=True)
    m = _mk(app_settings, session_factory, evo)
    _set_dest(session_factory, "111@g.us\n5511999")
    m.check_balance()
    assert evo.sent == ["5511999"]  # group skipped, number sent


def test_group_sent_when_other_is_last(app_settings, session_factory):
    evo = SpyEvo(last_from_me=False)
    m = _mk(app_settings, session_factory, evo)
    _set_dest(session_factory, "111@g.us\n5511999")
    m.check_balance()
    assert sorted(evo.sent) == ["111@g.us", "5511999"]


def test_group_sent_when_undetermined(app_settings, session_factory):
    evo = SpyEvo(last_from_me=None)  # fail-open
    m = _mk(app_settings, session_factory, evo)
    _set_dest(session_factory, "111@g.us")
    m.check_balance()
    assert evo.sent == ["111@g.us"]
