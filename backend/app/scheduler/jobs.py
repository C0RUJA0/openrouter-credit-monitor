"""In-process scheduler (APScheduler). Single worker owns it (spec section 20).

Runs the balance check on a fixed interval and prunes old events daily. The
check job coalesces and uses max_instances=1 so a slow check can't pile up.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings as AppSettings
from app.db import repository as repo
from app.services.monitor import MonitorService

logger = logging.getLogger("scheduler")

_CHECK_JOB_ID = "balance_check"
_PRUNE_JOB_ID = "prune_events"


class MonitorScheduler:
    def __init__(
        self,
        app_settings: AppSettings,
        monitor: MonitorService,
        session_factory,
    ) -> None:
        self._cfg = app_settings
        self._monitor = monitor
        self._session_factory = session_factory
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def _check_job(self) -> None:
        try:
            self._monitor.check_balance()
        except Exception:  # noqa: BLE001 - never let a job crash the scheduler
            logger.exception("scheduled balance check failed")

    def _prune_job(self) -> None:
        session = self._session_factory()
        try:
            deleted = repo.prune_events(session, self._cfg.event_retention_days)
            session.commit()
            if deleted:
                logger.info("pruned %s old events", deleted)
        except Exception:  # noqa: BLE001
            logger.exception("event prune failed")
        finally:
            session.close()

    def _interval_seconds(self) -> int:
        session = self._session_factory()
        try:
            return repo.get_settings(session).check_interval_seconds
        finally:
            session.close()

    def start(self) -> None:
        interval = self._interval_seconds()
        self._scheduler.add_job(
            self._check_job,
            trigger="interval",
            seconds=interval,
            id=_CHECK_JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._scheduler.add_job(
            self._prune_job,
            trigger="interval",
            hours=24,
            id=_PRUNE_JOB_ID,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("scheduler started (check interval %ss)", interval)

    def reschedule(self, interval_seconds: int) -> None:
        self._scheduler.reschedule_job(
            _CHECK_JOB_ID, trigger="interval", seconds=interval_seconds
        )
        logger.info("scheduler rescheduled to %ss", interval_seconds)

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("scheduler stopped")
