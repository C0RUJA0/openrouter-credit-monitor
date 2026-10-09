"""Monitor-driven WhatsApp pairing: create instance + fetch QR via Evolution."""
from __future__ import annotations

import httpx
import pytest

from app.services.evolution import EvolutionClient, EvolutionError
from app.services.monitor import MonitorService


class FakeEvo:
    def __init__(self, qr="data:image/png;base64,QUJD"):
        self.created = False
        self._qr = qr
    def create_instance(self):
        self.created = True
    def get_qr_base64(self):
        return self._qr
    def get_instance_status(self):
        return "DISCONNECTED"


def test_monitor_whatsapp_qr_creates_and_returns(app_settings, session_factory):
    evo = FakeEvo()
    m = MonitorService(app_settings, session_factory, evolution_client=evo)
    qr = m.whatsapp_qr()
    assert evo.created is True
    assert qr == "data:image/png;base64,QUJD"


def test_monitor_whatsapp_qr_requires_config(app_settings, session_factory):
    # no injected client and no evolution env/db config -> not configured
    app_settings.evolution_api_url = None
    app_settings.evolution_api_key = None
    app_settings.evolution_instance = None
    m = MonitorService(app_settings, session_factory)
    with pytest.raises(EvolutionError):
        m.whatsapp_qr()


def test_adapter_parses_qr_shapes():
    def handler(request):
        if request.url.path.endswith("/instance/create"):
            return httpx.Response(201, json={"instance": {"instanceName": "i"}})
        if "/instance/connect/" in request.url.path:
            return httpx.Response(200, json={"base64": "data:image/png;base64,ZZZ"})
        return httpx.Response(404)
    transport = httpx.MockTransport(handler)
    c = EvolutionClient("http://evo", "k", "i", transport=transport)
    c.create_instance()
    assert c.get_qr_base64() == "data:image/png;base64,ZZZ"


def test_adapter_parses_nested_qr_shape():
    def handler(request):
        return httpx.Response(200, json={"qrcode": {"base64": "data:image/png;base64,NEST"}})
    c = EvolutionClient("http://evo", "k", "i", transport=httpx.MockTransport(handler))
    assert c.get_qr_base64() == "data:image/png;base64,NEST"


from app.db import repository as repo
from app.services.monitor import parse_destinations


def test_parse_destinations_variants():
    assert parse_destinations(None) == []
    assert parse_destinations("  ") == []
    assert parse_destinations("5511999990000") == ["5511999990000"]
    assert parse_destinations("5511,5521\n5531; 5541") == ["5511", "5521", "5531", "5541"]
    assert parse_destinations("123@g.us\n123@g.us\n5511") == ["123@g.us", "5511"]


class MultiEvo:
    def __init__(self): self.sent = []
    def send_text(self, dest, text): self.sent.append(dest)
    def get_instance_status(self): return "CONNECTED"


def test_test_message_sends_to_all_targets(app_settings, session_factory):
    evo = MultiEvo()
    from app.services.monitor import MonitorService
    m = MonitorService(app_settings, session_factory, evolution_client=evo)
    s = session_factory()
    try:
        repo.get_settings(s).whatsapp_destination = "5511, 5521\n123@g.us"
        s.commit()
    finally:
        s.close()
    m.send_test_message()
    assert evo.sent == ["5511", "5521", "123@g.us"]


def test_alert_sends_to_all_targets(app_settings, session_factory):
    from decimal import Decimal
    evo = MultiEvo()
    from app.services.monitor import MonitorService

    class FakeOR:
        def get_credits(self):
            from app.services.openrouter import CreditsResult
            return CreditsResult(total_credits=Decimal("5"), total_usage=Decimal("0"))

    m = MonitorService(app_settings, session_factory, openrouter_client=FakeOR(), evolution_client=evo)
    s = session_factory()
    try:
        repo.get_settings(s).whatsapp_destination = "5511\n5521"
        s.commit()
    finally:
        s.close()
    m.check_balance()  # 5 <= 10 -> alert to all
    assert sorted(evo.sent) == ["5511", "5521"]


def test_fetch_groups_parses_list():
    def handler(request):
        assert "/group/fetchAllGroups/" in request.url.path
        return httpx.Response(200, json=[
            {"id": "111@g.us", "subject": "Família"},
            {"id": "222@g.us", "subject": "Trabalho"},
            {"id": "", "subject": "sem id"},
            {"id": "333@g.us"},
        ])
    c = EvolutionClient("http://evo", "k", "inst", transport=httpx.MockTransport(handler))
    groups = c.fetch_groups()
    assert groups == [
        {"id": "111@g.us", "name": "Família"},
        {"id": "222@g.us", "name": "Trabalho"},
        {"id": "333@g.us", "name": "333@g.us"},
    ]


def test_list_groups_best_effort_empty_on_error(app_settings, session_factory):
    from app.services.monitor import MonitorService

    class BoomEvo:
        def fetch_groups(self): raise EvolutionError("down")
        def get_instance_status(self): return "CONNECTED"
    m = MonitorService(app_settings, session_factory, evolution_client=BoomEvo())
    assert m.list_whatsapp_groups() == []
