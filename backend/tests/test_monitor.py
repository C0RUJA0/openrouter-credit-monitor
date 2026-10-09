import threading
import time
from datetime import datetime
from decimal import Decimal

import pytest

from app.db import repository as repo
from app.events import EventType, OpenRouterStatus
from app.services.evolution import EvolutionError
from app.services.monitor import MonitorService
from app.services.openrouter import CreditsResult, OpenRouterError


class FakeOpenRouter:
    def __init__(self, balance="25.00"):
        self.set_balance(balance)
        self.raise_error = False
        self.delay = 0.0

    def set_balance(self, balance):
        self._credits = CreditsResult(
            total_credits=Decimal(str(balance)), total_usage=Decimal("0")
        )

    def get_credits(self):
        if self.delay:
            time.sleep(self.delay)
        if self.raise_error:
            raise OpenRouterError("boom")
        return self._credits


class FakeEvolution:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send_text(self, destination, text):
        if self.fail:
            raise EvolutionError("send failed")
        self.sent.append((destination, text))

    def get_instance_status(self):
        return "CONNECTED"


def _monitor(cfg, sf, orc, evo, now_fn=None):
    kwargs = {"openrouter_client": orc, "evolution_client": evo}
    if now_fn:
        kwargs["now_fn"] = now_fn
    return MonitorService(cfg, sf, **kwargs)


def _count_events(sf, event_type):
    s = sf()
    try:
        return sum(1 for e in repo.recent_events(s, limit=500) if e.event_type == event_type)
    finally:
        s.close()


def _state(sf):
    s = sf()
    try:
        st = repo.get_state(s)
        s.expunge(st)
        return st
    finally:
        s.close()


def test_scenario_a_normal(app_settings, session_factory):
    orc, evo = FakeOpenRouter("25.00"), FakeEvolution()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()
    st = _state(session_factory)
    assert st.last_balance == Decimal("25.00")
    assert st.openrouter_status == OpenRouterStatus.ONLINE
    assert st.alert_triggered is False
    assert evo.sent == []


def test_scenario_b_crossing_sends_once(app_settings, session_factory):
    orc, evo = FakeOpenRouter("9.90"), FakeEvolution()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()
    assert len(evo.sent) == 1
    assert _state(session_factory).alert_triggered is True
    assert _count_events(session_factory, EventType.ALERT_SENT) == 1


def test_scenario_c_stays_low_no_repeat(app_settings, session_factory):
    orc, evo = FakeOpenRouter("9.90"), FakeEvolution()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()
    orc.set_balance("8.00")
    m.check_balance()
    orc.set_balance("7.00")
    m.check_balance()
    assert len(evo.sent) == 1  # no new messages


def test_scenario_d_e_rearm_then_second_alert(app_settings, session_factory):
    orc, evo = FakeOpenRouter("9.90"), FakeEvolution()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()                      # alert 1
    orc.set_balance("30.00")
    m.check_balance()                      # rearm
    assert _state(session_factory).alert_triggered is False
    assert _count_events(session_factory, EventType.ALERT_REARMED) == 1
    orc.set_balance("9.00")
    m.check_balance()                      # alert 2
    assert len(evo.sent) == 2


def test_scenario_f_openrouter_error_keeps_last_balance(app_settings, session_factory):
    orc, evo = FakeOpenRouter("25.00"), FakeEvolution()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()
    orc.raise_error = True
    m.check_balance()
    st = _state(session_factory)
    assert st.last_balance == Decimal("25.00")        # not zeroed
    assert st.openrouter_status == OpenRouterStatus.ERROR
    assert evo.sent == []
    assert _count_events(session_factory, EventType.OPENROUTER_ERROR) == 1


def test_scenario_g_evolution_failure_no_trigger_and_backoff(app_settings, session_factory):
    orc, evo = FakeOpenRouter("9.00"), FakeEvolution()
    evo.fail = True
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()
    st = _state(session_factory)
    assert st.alert_triggered is False
    assert st.alert_attempt_count == 1
    assert st.next_retry_at is not None
    assert _count_events(session_factory, EventType.WHATSAPP_ERROR) == 1


def test_scenario_g_no_rapid_retry_within_backoff(app_settings, session_factory):
    orc, evo = FakeOpenRouter("9.00"), FakeEvolution()
    evo.fail = True
    fixed = datetime(2026, 1, 1, 12, 0, 0)
    m = _monitor(app_settings, session_factory, orc, evo, now_fn=lambda: fixed)
    m.check_balance()
    m.check_balance()  # same instant -> within backoff window, no new attempt
    # only one failure recorded because second check skipped the send
    assert _count_events(session_factory, EventType.WHATSAPP_ERROR) == 1
    assert _state(session_factory).alert_attempt_count == 1


def test_scenario_g_recovers_after_backoff_elapses(app_settings, session_factory):
    orc, evo = FakeOpenRouter("9.00"), FakeEvolution()
    evo.fail = True
    clock = {"t": datetime(2026, 1, 1, 12, 0, 0)}
    m = _monitor(app_settings, session_factory, orc, evo, now_fn=lambda: clock["t"])
    m.check_balance()                      # fail, next retry +60s
    clock["t"] = datetime(2026, 1, 1, 12, 2, 0)  # +120s, backoff elapsed
    evo.fail = False
    m.check_balance()                      # should send now
    assert len(evo.sent) == 1
    assert _state(session_factory).alert_triggered is True


def test_scenario_h_restart_no_duplicate(app_settings, session_factory):
    orc, evo = FakeOpenRouter("8.00"), FakeEvolution()
    m1 = _monitor(app_settings, session_factory, orc, evo)
    m1.check_balance()                     # alert sent, triggered persisted
    assert len(evo.sent) == 1
    # simulate restart: brand new service + client on SAME db
    evo2 = FakeEvolution()
    m2 = _monitor(app_settings, session_factory, FakeOpenRouter("8.00"), evo2)
    m2.check_balance()
    assert evo2.sent == []                 # no duplicate after restart
    assert _state(session_factory).alert_triggered is True


def test_threshold_change_reevaluates(app_settings, session_factory):
    orc, evo = FakeOpenRouter("12.00"), FakeEvolution()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()                      # 12 > 10, no alert
    assert evo.sent == []
    # raise threshold to 15 -> 12 now below -> reevaluate should alert once
    s = session_factory()
    try:
        repo.get_settings(s).alert_threshold = Decimal("15.00")
        s.commit()
    finally:
        s.close()
    m.reevaluate_now()
    assert len(evo.sent) == 1


def test_notifications_disabled_no_send(app_settings, session_factory):
    orc, evo = FakeOpenRouter("5.00"), FakeEvolution()
    s = session_factory()
    try:
        repo.get_settings(s).notifications_enabled = False
        s.commit()
    finally:
        s.close()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.check_balance()
    assert evo.sent == []
    assert _state(session_factory).alert_triggered is False


def test_concurrent_checks_single_alert(app_settings, session_factory):
    orc, evo = FakeOpenRouter("9.00"), FakeEvolution()
    orc.delay = 0.3
    m = _monitor(app_settings, session_factory, orc, evo)

    results = []

    def run():
        results.append(m.check_balance())

    t1 = threading.Thread(target=run)
    t2 = threading.Thread(target=run)
    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join()
    t2.join()

    ran_flags = sorted(r.ran for r in results)
    assert ran_flags == [False, True]      # one ran, one was busy
    assert len(evo.sent) == 1


def test_send_test_message_does_not_touch_trigger(app_settings, session_factory):
    orc, evo = FakeOpenRouter("25.00"), FakeEvolution()
    m = _monitor(app_settings, session_factory, orc, evo)
    m.send_test_message()
    assert len(evo.sent) == 1
    assert _state(session_factory).alert_triggered is False
    assert _count_events(session_factory, EventType.WHATSAPP_TEST_SENT) == 1
