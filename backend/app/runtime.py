"""Process-wide singletons wired at startup and used by routers/scheduler."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.config import Settings as AppSettings
from app.scheduler.jobs import MonitorScheduler
from app.services.monitor import MonitorService


@dataclass
class Runtime:
    config: AppSettings
    session_factory: Callable
    monitor: MonitorService
    scheduler: MonitorScheduler | None = None


_runtime: Runtime | None = None


def set_runtime(runtime: Runtime) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> Runtime:
    if _runtime is None:
        raise RuntimeError("Runtime not initialized")
    return _runtime


def clear_runtime() -> None:
    global _runtime
    _runtime = None
