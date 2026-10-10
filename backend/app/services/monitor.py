"""Monitor orchestration — the single check function used by both the scheduler
and the "Verificar agora" button. No duplicated logic (spec section 4).

Concurrency: a non-blocking lock guarantees at most one check runs at a time,
so two near-simultaneous checks can never send two alerts (spec sections 20, 25).
State (`alert_triggered`) is persisted in SQLite, so a restart never re-sends
an alert for a balance that is still low (spec section 26).
"""
from __future__ import annotations

import logging
import re
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


def parse_destinations(raw: str | None) -> list[str]:
    """Split a destination string into individual targets.

    Accepts multiple numbers and/or WhatsApp group IDs (``...@g.us``) separated
    by comma, semicolon, or newline. Order preserved, duplicates removed.
    """
    if not raw:
        return []
    out: list[str] = []
    for part in re.split(r"[,;\n\r]+", raw):
        target = part.strip()
        if target and target not in out:
            out.append(target)
    return out


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

    def _effective_openrouter_key(self, settings_row) -> str | None:
        """Prefer the UI-set DB override, else the environment key."""
        db_key = getattr(settings_row, "openrouter_key", None)
        if db_key:
            return db_key
        return self._cfg.openrouter_management_key

    def _openrouter_client(self, key: str | None = None) -> OpenRouterClient:
        if self._openrouter is not None:
            return self._openrouter
        if not key:
            # Surface as an OpenRouterError so a missing key degrades to the
            # normal error path (UNKNOWN status) instead of crashing a check.
            raise OpenRouterError("OpenRouter key not configured")
        return OpenRouterClient(
            self._cfg.openrouter_base_url,
            key,
            timeout=self._cfg.http_timeout,
        )

    def _effective_evolution(self, settings_row) -> dict:
        """Resolve each Evolution field: DB override if present, else env."""
        g = lambda name: getattr(settings_row, name, None)  # noqa: E731
        return {
            "url": g("evolution_api_url") or self._cfg.evolution_api_url,
            "key": g("evolution_api_key") or self._cfg.evolution_api_key,
            "instance": g("evolution_instance") or self._cfg.evolution_instance,
            "destination": g("whatsapp_destination") or self._cfg.whatsapp_destination,
        }

    def _evolution_client(self, settings_row=None) -> EvolutionClient | None:
        if self._evolution is not None:
            return self._evolution
        if settings_row is not None:
            evo = self._effective_evolution(settings_row)
            url, key, instance = evo["url"], evo["key"], evo["instance"]
        else:
            url = self._cfg.evolution_api_url
            key = self._cfg.evolution_api_key
            instance = self._cfg.evolution_instance
        if not (url and key and instance):
            return None
        return EvolutionClient(url, key, instance, timeout=self._cfg.http_timeout)

    def _effective_destination(self, settings_row=None) -> str | None:
        if settings_row is not None:
            return getattr(settings_row, "whatsapp_destination", None) or self._cfg.whatsapp_destination
        return self._cfg.whatsapp_destination

    def _effective_destinations(self, settings_row=None) -> list[str]:
        """All send targets (numbers and/or group IDs) for this config."""
        return parse_destinations(self._effective_destination(settings_row))

    def _filter_group_antispam(self, client, targets: list[str]) -> list[str]:
        """Drop group targets whose last message is already the bot's own, to
        avoid stacking consecutive bot messages. Fail-open: on None/error keep
        the target. Numbers are never filtered."""
        if not self._cfg.group_antispam_check:
            return targets
        out: list[str] = []
        for t in targets:
            if t.endswith("@g.us"):
                try:
                    if client.last_message_is_from_me(t) is True:
                        logger.info("group %s: bot is last message, skipping", t)
                        continue
                except EvolutionError:
                    pass  # fail-open: send anyway
            out.append(t)
        return out

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

    def whatsapp_qr(self) -> str | None:
        """Ensure the instance exists and return its pairing QR (base64 PNG data
        URI), or None if already connected / no QR. Raises EvolutionError when
        Evolution is unreachable or not configured."""
        session = self._session_factory()
        try:
            settings_row = repo.get_settings(session)
            client = self._evolution_client(settings_row)
            if client is None:
                raise EvolutionError("Evolution API not configured")
            client.create_instance()
            return client.get_qr_base64()
        finally:
            session.close()

    def list_whatsapp_groups(self) -> list[dict]:
        """Best-effort list of WhatsApp groups for the UI selector. Returns [] if
        Evolution is unconfigured/unreachable or no instance is connected."""
        session = self._session_factory()
        try:
            settings_row = repo.get_settings(session)
            client = self._evolution_client(settings_row)
            if client is None:
                return []
            try:
                return client.fetch_groups()
            except EvolutionError:
                return []
        finally:
            session.close()

    def send_test_message(self) -> None:
        """Send a WhatsApp test message. Does NOT touch alert_triggered."""
        session = self._session_factory()
        try:
            settings_row = repo.get_settings(session)
            state = repo.get_state(session)
            client = self._evolution_client(settings_row)
            if client is None:
                repo.add_event(
                    session,
                    EventType.WHATSAPP_ERROR,
                    message="Evolution API not configured",
                )
                state.evolution_status = EvolutionStatus.UNKNOWN
                session.commit()
                raise EvolutionError("Evolution API not configured")
            targets = self._effective_destinations(settings_row)
            if not targets:
                repo.add_event(session, EventType.WHATSAPP_ERROR, message="no destination configured")
                session.commit()
                raise EvolutionError("no destination configured")
            try:
                for target in targets:
                    client.send_text(
                        target,
                        "✅ *OpenRouter Credit Monitor*\n"
                        "━━━━━━━━━━━━━━━\n"
                        "Mensagem de teste enviada com sucesso! 🎉\n\n"
                        "📡 _Integração WhatsApp funcionando._",
                    )
            except EvolutionError:
                repo.add_event(session, EventType.WHATSAPP_ERROR, message="test send failed")
                state.evolution_status = EvolutionStatus.ERROR
                session.commit()
                raise
            repo.add_event(
                session, EventType.WHATSAPP_TEST_SENT,
                message=f"test message sent to {len(targets)} target(s)",
            )
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
                key = self._effective_openrouter_key(settings_row)
                credits = self._openrouter_client(key).get_credits()
            except OpenRouterError as exc:
                # An error is NOT a zero balance. Preserve last known balance.
                state.openrouter_status = OpenRouterStatus.ERROR
                repo.add_event(
                    session,
                    EventType.OPENROUTER_ERROR,
                    message=str(exc),
                )
                self._refresh_evolution_status(state, settings_row)
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

            self._refresh_evolution_status(state, settings_row)
            self._apply_decision(session, settings_row, state, balance)
            session.commit()
            return CheckResult(ran=True, detail="ok")
        finally:
            session.close()

    def _refresh_evolution_status(self, state, settings_row=None) -> None:
        client = self._evolution_client(settings_row)
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
            # Balance recovered above the threshold -> reset the daily reminder
            # window so the next low episode can alert again.
            state.alert_window_start = None
            state.alert_sends_in_window = 0
            repo.add_event(
                session,
                EventType.BALANCE_RECOVERED,
                balance=balance,
                message=f"balance recovered to {format_usd(balance)}",
            )
            repo.add_event(session, EventType.ALERT_REARMED, balance=balance)
            return

        if decision.action == AlertAction.SEND_ALERT:
            # First alert of this low episode — always send (counts as #1/day).
            self._try_send_alert(session, settings_row, state, balance)
            return

        # Still low and already alerted: send a reminder if under the daily cap
        # and enough time has passed since the last alert (anti-spam).
        if (
            decision.is_low
            and state.alert_triggered
            and settings_row.notifications_enabled
            and self._reminder_allowed(state, self._now())
        ):
            self._try_send_alert(session, settings_row, state, balance)

    def _reminder_allowed(self, state, now: datetime) -> bool:
        """True if a reminder may be sent now: under the daily cap AND spaced far
        enough from the last alert. A stale (>24h) window counts as reset."""
        count = state.alert_sends_in_window or 0
        if state.alert_window_start is not None and \
                (now - state.alert_window_start).total_seconds() >= 86400:
            count = 0
        if count >= self._cfg.alert_max_per_day:
            return False
        if state.last_alert_at is not None and \
                (now - state.last_alert_at).total_seconds() < self._cfg.alert_reminder_gap_seconds:
            return False
        return True

    def _record_alert_send(self, state, now: datetime) -> None:
        """Account one successful alert send against the rolling 24h window."""
        if state.alert_window_start is None or \
                (now - state.alert_window_start).total_seconds() >= 86400:
            state.alert_window_start = now
            state.alert_sends_in_window = 0
        state.alert_sends_in_window = (state.alert_sends_in_window or 0) + 1

    def _try_send_alert(self, session, settings_row, state, balance: Decimal) -> None:
        now = self._now()
        # Respect backoff: don't retry before next_retry_at (anti-spam).
        if state.next_retry_at is not None and now < state.next_retry_at:
            return

        client = self._evolution_client(settings_row)
        if client is None:
            self._record_send_failure(session, state, now, "Evolution API not configured")
            return

        targets = self._effective_destinations(settings_row)
        if not targets:
            self._record_send_failure(session, state, now, "no destination configured")
            return

        # Group anti-spam: drop groups where the bot is already the last message.
        targets = self._filter_group_antispam(client, targets)
        if not targets:
            logger.info("all targets suppressed by group anti-spam; skipping send")
            return

        text = self._format_alert(balance, settings_row.alert_threshold)
        try:
            for target in targets:
                client.send_text(target, text)
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
        self._record_alert_send(state, now)
        repo.add_event(
            session,
            EventType.ALERT_SENT,
            balance=balance,
            message=f"alert sent at {format_usd(balance)} "
                    f"({state.alert_sends_in_window}/{self._cfg.alert_max_per_day} today)",
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
            "🚨 *OpenRouter — Créditos baixos* 🚨\n"
            "━━━━━━━━━━━━━━━\n"
            "Seu saldo atingiu o limite configurado.\n\n"
            f"💰 *Saldo atual:*  {format_usd(balance)}\n"
            f"🎯 *Limite:*  {format_usd(threshold)}\n"
            "━━━━━━━━━━━━━━━\n"
            "⚡ _Recarregue para evitar interrupções._"
        )
