"""Pure alert-engine logic — no DB, no HTTP, fully unit-testable.

The alert is edge-triggered on the threshold crossing, not level-triggered:
it fires once when balance first drops to/below the threshold, and only re-arms
when balance rises back above it. See spec sections 5, 6, 29.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.events import BalanceStatus


class AlertAction:
    NONE = "NONE"
    SEND_ALERT = "SEND_ALERT"
    REARM = "REARM"


@dataclass(frozen=True)
class AlertDecision:
    action: str
    balance_status: str
    is_low: bool


def evaluate(
    *,
    balance: Decimal | None,
    threshold: Decimal,
    alert_triggered: bool,
    notifications_enabled: bool,
) -> AlertDecision:
    """Decide what the monitor should do given current balance and persisted state.

    - balance is None  -> UNKNOWN, never alert (an error is not a zero balance).
    - balance <= threshold and not yet triggered -> SEND_ALERT (if notifications on).
    - balance  > threshold and currently triggered -> REARM.
    - otherwise -> NONE.
    """
    if balance is None:
        return AlertDecision(AlertAction.NONE, BalanceStatus.UNKNOWN, is_low=False)

    is_low = balance <= threshold
    status = BalanceStatus.LOW if is_low else BalanceStatus.NORMAL

    if is_low and not alert_triggered:
        action = AlertAction.SEND_ALERT if notifications_enabled else AlertAction.NONE
        return AlertDecision(action, status, is_low=True)

    if not is_low and alert_triggered:
        return AlertDecision(AlertAction.REARM, status, is_low=False)

    return AlertDecision(AlertAction.NONE, status, is_low=is_low)
