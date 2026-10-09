"""Monitor orchestration — the single check function used by both the scheduler
and the "Verificar agora" button. No duplicated logic (spec section 4).

Concurrency: a non-blocking lock guarantees at most one check runs at a time,
so two near-simultaneous checks can never send two alerts (spec sections 20, 25).
State (`alert_triggered`) is persisted in SQLite, so a restart never re-sends
an alert for a balance that is still low (spec section 26).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable

from app.config import Settings as AppSettings
from app.db import repository as repo
from app.db.models import utcnow
from app.events import EventType, EvolutionStatus, OpenRouterStatus
from app.money import format_usd
from app.services.alerts import AlertAction, evaluate
from app.services.evolution import EvolutionClient, EvolutionError
from app.services.openrouter import OpenRouterClient, OpenRouterError

logger = logging.getLogger("monitor")

# WhatsApp send-failure backoff: delay before the Nth retry is allowed.
# Attempt 1 is immediate; after it fails wait 60s, then 300s, then cap at 300s.
_BACKOFF_SECONDS = [60, 300, 300]


class CheckResult:
    def __init__(self, ran: bool, detail: str = "") -> None:
        self.ran = ran
        self.detail = detail


def _backoff_delay(attempt_count: int) -> int:
    idx = min(max(attempt_count - 1, 0), len(_BACKOFF_SECONDS) - 1)
    return _BACKOFF_SECONDS[idx]


class MonitorService:
    def __init__(
        self,
        app_settings: AppSettings,
        session_factory: Callable,
        *,
        openrouter_client: OpenRouterClient | None = None,
        evolution_client: EvolutionClient | None = None,
        now_fn: Callable[[], datetime] = utcnow,
    ) -> None:
        self._cfg = app_settings
        self._session_factory = session_factory
        self._openrouter = openrouter_client
        self._evolution = evolution_client
        self._now = now_fn
        self._lock = threading.Lock()

    # -- client accessors (lazy build from config) ------------------------

    def _openrouter_client(self) -> OpenRouterClient:
        if self._openrouter is not None:
            return self._openrouter
        if not self._cfg.openrouter_management_key:
            # Surface as an OpenRouterError so a missing key degrades to the
            # normal error path (UNKNOWN status) instead of crashing a check.
            raise OpenRouterError("OPENROUTER_MANAGEMENT_KEY not configured")
        return OpenRouterClient(
            self._cfg.openrouter_base_url,
            self._cfg.openrouter_management_key,
            timeout=self._cfg.http_timeout,
        )

    def _evolution_client(self) -> EvolutionClient | None:
        if self._evolution is not None:
            return self._evolution
        if not (
            self._cfg.evolution_api_url
            and self._cfg.evolution_api_key
            and self._cfg.evolution_instance
        ):
            return None
        return EvolutionClient(
            self._cfg.evolution_api_url,
            self._cfg.evolution_api_key,
            self._cfg.evolution_instance,
            timeout=self._cfg.http_timeout,
        )

    # -- public API -------------------------------------------------------

    def check_balance(self) -> CheckResult:
        """Fetch balance from OpenRouter, update state, evaluate alert rule.

        Returns a CheckResult; `ran=False` means another check held the lock.
        """
        if not self._lock.acquire(blocking=False):
            logger.info("check skipped: another check is in progress")
            return CheckResult(ran=False, detail="busy")
        try:
            return self._do_check()
        finally:
            self._lock.release()

    def reevaluate_now(self) -> CheckResult:
        """Re-apply the alert rule against the last known balance WITHOUT a
        network call. Used after a threshold change or notifications toggle.
        Respects `alert_triggered`, so it never spams."""
        if not self._lock.acquire(blocking=False):
            return CheckResult(ran=False, detail="busy")
        try:
            session = self._session_factory()
            try:
                settings_row = repo.get_settings(session)
                state = repo.get_state(session)
                self._apply_decision(session, settings_row, state, state.last_balance)
                session.commit()
                return CheckResult(ran=True, detail="reevaluated")
            finally:
                session.close()
        finally:
            self._lock.release()

    def send_test_message(self) -> None:
        """Send a WhatsApp test message. Does NOT touch alert_triggered."""
        session = self._session_factory()
        try:
            state = repo.get_state(session)
            client = self._evolution_client()
            if client is None:
                repo.add_event(
                    session,
                    EventType.WHATSAPP_ERROR,
                    message="Evolution API not configured",
                )
                state.evolution_status = EvolutionStatus.UNKNOWN
                session.commit()
                raise EvolutionError("Evolution API not configured")
            try:
                client.send_text(
                    self._cfg.whatsapp_destination,
                    "✅ OpenRouter Credit Monitor\n\nMensagem de teste enviada com sucesso.",
                )
            except EvolutionError:
                repo.add_event(session, EventType.WHATSAPP_ERROR, message="test send failed")
                state.evolution_status = EvolutionStatus.ERROR
                session.commit()
                raise
            repo.add_event(session, EventType.WHATSAPP_TEST_SENT, message="test message sent")
            session.commit()
        finally:
            session.close()

    # -- internals --------------------------------------------------------

    def _do_check(self) -> CheckResult:
        session = self._session_factory()
        try:
            settings_row = repo.get_settings(session)
            state = repo.get_state(session)
            now = self._now()
            state.last_check_at = now

            try:
                credits = self._openrouter_client().get_credits()
            except OpenRouterError as exc:
                # An error is NOT a zero balance. Preserve last known balance.
                state.openrouter_status = OpenRouterStatus.ERROR
                repo.add_event(
                    session,
                    EventType.OPENROUTER_ERROR,
                    message=str(exc),
                )
                self._refresh_evolution_status(state)
                session.commit()
                logger.warning("openrouter check failed: %s", exc)
                return CheckResult(ran=True, detail="openrouter_error")

            balance = credits.balance
            state.last_balance = balance
            state.last_total_credits = credits.total_credits
            state.last_total_usage = credits.total_usage
            state.last_success_at = now
            state.openrouter_status = OpenRouterStatus.ONLINE
            repo.add_event(
                session,
                EventType.BALANCE_CHECK,
                balance=balance,
                message=f"balance {format_usd(balance)}",
            )

            self._refresh_evolution_status(state)
            self._apply_decision(session, settings_row, state, balance)
            session.commit()
            return CheckResult(ran=True, detail="ok")
        finally:
            session.close()

    def _refresh_evolution_status(self, state) -> None:
        client = self._evolution_client()
        if client is None:
            state.evolution_status = EvolutionStatus.UNKNOWN
            return
        try:
            state.evolution_status = client.get_instance_status()
        except Exception:  # noqa: BLE001 - status is best-effort, never fatal
            state.evolution_status = EvolutionStatus.ERROR

    def _apply_decision(self, session, settings_row, state, balance: Decimal | None) -> None:
        decision = evaluate(
            balance=balance,
            threshold=settings_row.alert_threshold,
            alert_triggered=state.alert_triggered,
            notifications_enabled=settings_row.notifications_enabled,
        )

        if decision.action == AlertAction.REARM:
            state.alert_triggered = False
            state.alert_attempt_count = 0
            state.next_retry_at = None
            repo.add_event(
                session,
                EventType.BALANCE_RECOVERED,
                balance=balance,
                message=f"balance recovered to {format_usd(balance)}",
            )
            repo.add_event(session, EventType.ALERT_REARMED, balance=balance)
            return

        if decision.action == AlertAction.SEND_ALERT:
            self._try_send_alert(session, settings_row, state, balance)

    def _try_send_alert(self, session, settings_row, state, balance: Decimal) -> None:
        now = self._now()
        # Respect backoff: don't retry before next_retry_at (anti-spam).
        if state.next_retry_at is not None and now < state.next_retry_at:
            return

        client = self._evolution_client()
        if client is None:
            self._record_send_failure(session, state, now, "Evolution API not configured")
            return

        text = self._format_alert(balance, settings_row.alert_threshold)
        try:
            client.send_text(self._cfg.whatsapp_destination, text)
        except EvolutionError as exc:
            self._record_send_failure(session, state, now, str(exc))
            return

        # Success: mark alert sent (ONLY after confirmed success).
        state.alert_triggered = True
        state.last_alert_at = now
        state.last_alert_balance = balance
        state.alert_attempt_count = 0
        state.next_retry_at = None
        state.evolution_status = EvolutionStatus.CONNECTED
        repo.add_event(
            session,
            EventType.ALERT_SENT,
            balance=balance,
            message=f"alert sent at {format_usd(balance)}",
        )

    def _record_send_failure(self, session, state, now: datetime, detail: str) -> None:
        state.alert_attempt_count = (state.alert_attempt_count or 0) + 1
        delay = _backoff_delay(state.alert_attempt_count)
        state.next_retry_at = now + timedelta(seconds=delay)
        state.evolution_status = EvolutionStatus.ERROR
        # alert_triggered deliberately stays False so a successful future send
        # can still fire the alert.
        repo.add_event(
            session,
            EventType.WHATSAPP_ERROR,
            balance=state.last_balance,
            message="whatsapp send failed",
            metadata={"attempt": state.alert_attempt_count, "retry_in_s": delay},
        )
        logger.warning("whatsapp send failed (attempt %s): %s", state.alert_attempt_count, detail)

    @staticmethod
    def _format_alert(balance: Decimal, threshold: Decimal) -> str:
        return (
            "🚨 OpenRouter — Créditos baixos\n\n"
            "Seu saldo chegou ao limite configurado.\n\n"
            f"Saldo atual: {format_usd(balance)}\n"
            f"Limite: {format_usd(threshold)}"
        )
