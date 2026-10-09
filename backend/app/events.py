"""Event type constants. Use these instead of scattering string literals."""
from __future__ import annotations


class EventType:
    BALANCE_CHECK = "BALANCE_CHECK"
    BALANCE_RECOVERED = "BALANCE_RECOVERED"
    ALERT_SENT = "ALERT_SENT"
    ALERT_REARMED = "ALERT_REARMED"
    OPENROUTER_ERROR = "OPENROUTER_ERROR"
    WHATSAPP_TEST_SENT = "WHATSAPP_TEST_SENT"
    WHATSAPP_ERROR = "WHATSAPP_ERROR"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    MONITOR_STARTED = "MONITOR_STARTED"


class OpenRouterStatus:
    ONLINE = "ONLINE"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class EvolutionStatus:
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class BalanceStatus:
    NORMAL = "NORMAL"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"
