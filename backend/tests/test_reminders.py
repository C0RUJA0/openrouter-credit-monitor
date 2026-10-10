"""Daily reminder cap: up to N alerts per rolling 24h while low, spaced apart,
reset when balance recovers above threshold."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.db import repository as repo
from app.services.monitor import MonitorService
from app.services.openrouter import CreditsResult


class FakeOR:
    def __init__(self, bal="5.00"): self.bal = Decimal(bal)
    def get_credits(self): return CreditsResult(total_credits=self.bal, total_usage=Decimal("0"))


class FakeEvo:
    def __init__(self): self.sent = []
    def send_text(self, dest, text): self.sent.append((dest, text))
    def get_instance_status(self): return "CONNECTED"


def _mk(app_settings, sf, clock):
    app_settings.alert_max_per_day = 2
    app_settings.alert_reminder_gap_seconds = 21600  # 6h
    return MonitorService(app_settings, sf, openrouter_client=FakeOR(), evolution_client=FakeEvo(),
                          now_fn=lambda: clock["t"])


def test_two_reminders_per_day_then_capped(app_settings, session_factory):
    clock = {"t": datetime(2026, 1, 1, 0, 0, 0)}
    m = _mk(app_settings, session_factory, clock)
    evo = m._evolution

    m.check_balance()                       # t0: first alert (1/2)
    assert len(evo.sent) == 1

    clock["t"] += timedelta(hours=3)        # +3h: within gap -> no send
    m.check_balance()
    assert len(evo.sent) == 1

    clock["t"] += timedelta(hours=4)        # +7h total: gap elapsed -> reminder (2/2)
    m.check_balance()
    assert len(evo.sent) == 2

    clock["t"] += timedelta(hours=7)        # +14h: cap reached -> no send
    m.check_balance()
    assert len(evo.sent) == 2


def test_window_resets_after_24h(app_settings, session_factory):
    clock = {"t": datetime(2026, 1, 1, 0, 0, 0)}
    m = _mk(app_settings, session_factory, clock)
    evo = m._evolution
    m.check_balance()                       # 1/2
    clock["t"] += timedelta(hours=7); m.check_balance()   # 2/2
    assert len(evo.sent) == 2
    clock["t"] += timedelta(hours=25)       # new 24h window
    m.check_balance()                       # allowed again (1/2 of new day)
    assert len(evo.sent) == 3


def test_recovery_resets_reminder_count(app_settings, session_factory):
    clock = {"t": datetime(2026, 1, 1, 0, 0, 0)}
    m = _mk(app_settings, session_factory, clock)
    evo = m._evolution
    m.check_balance()                       # low -> alert 1
    # balance recovers above threshold -> rearm
    m._openrouter.bal = Decimal("50.00")
    clock["t"] += timedelta(hours=1); m.check_balance()
    st = session_factory()
    try:
        assert repo.get_state(st).alert_sends_in_window == 0
    finally:
        st.close()
    # drops again -> fresh episode alerts immediately
    m._openrouter.bal = Decimal("5.00")
    clock["t"] += timedelta(hours=1); m.check_balance()
    assert len(evo.sent) == 2
