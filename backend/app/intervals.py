"""Human-friendly interval units <-> seconds.

The check interval is stored in SQLite as seconds. The UI edits it as a value +
unit (seg/min/h/dias/sem/mês). These helpers convert both ways.
"""
from __future__ import annotations

# Unit key -> seconds. "mes" = 30 days (approx, fine for a poll interval).
UNIT_SECONDS: dict[str, int] = {
    "seg": 1,
    "min": 60,
    "h": 3600,
    "dias": 86400,
    "sem": 604800,
    "mes": 2592000,
}

# Largest-first, for picking the nicest display unit.
_ORDER = ["mes", "sem", "dias", "h", "min", "seg"]

# Labels for the UI (value -> display text).
UNIT_LABELS: dict[str, str] = {
    "seg": "segundos", "min": "minutos", "h": "horas",
    "dias": "dias", "sem": "semanas", "mes": "meses",
}


def to_seconds(value: int, unit: str) -> int:
    """Convert value+unit to seconds. Unknown unit falls back to seconds."""
    return int(value) * UNIT_SECONDS.get(unit, 1)


def split(seconds: int) -> tuple[int, str]:
    """Pick the largest unit that divides `seconds` evenly -> (value, unit)."""
    seconds = int(seconds)
    if seconds <= 0:
        return (0, "seg")
    for unit in _ORDER:
        step = UNIT_SECONDS[unit]
        if seconds % step == 0:
            return (seconds // step, unit)
    return (seconds, "seg")
