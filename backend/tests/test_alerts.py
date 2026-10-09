from decimal import Decimal

import pytest

from app.events import BalanceStatus
from app.services.alerts import AlertAction, evaluate

T = Decimal("10.00")


def _eval(balance, triggered=False, notifications=True):
    bal = None if balance is None else Decimal(str(balance))
    return evaluate(
        balance=bal,
        threshold=T,
        alert_triggered=triggered,
        notifications_enabled=notifications,
    )


def test_above_threshold_no_alert():
    d = _eval("25")
    assert d.action == AlertAction.NONE
    assert d.balance_status == BalanceStatus.NORMAL


def test_equal_threshold_triggers_alert():
    # 10 / limite 10 -> alerta
    assert _eval("10.00").action == AlertAction.SEND_ALERT


def test_below_threshold_triggers_alert():
    assert _eval("9.00").action == AlertAction.SEND_ALERT


def test_no_repeat_while_low():
    # already triggered, stays low -> nothing
    assert _eval("8.00", triggered=True).action == AlertAction.NONE


def test_rearm_when_recovered():
    d = _eval("30.00", triggered=True)
    assert d.action == AlertAction.REARM
    assert d.balance_status == BalanceStatus.NORMAL


def test_unknown_balance_never_alerts():
    d = _eval(None)
    assert d.action == AlertAction.NONE
    assert d.balance_status == BalanceStatus.UNKNOWN


def test_notifications_disabled_suppresses_send():
    d = _eval("9.00", notifications=False)
    assert d.action == AlertAction.NONE
    assert d.is_low is True


def test_rearm_happens_even_if_notifications_disabled():
    # rearm is bookkeeping, not a message
    assert _eval("30.00", triggered=True, notifications=False).action == AlertAction.REARM
