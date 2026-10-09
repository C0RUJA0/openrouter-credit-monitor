"""Custom SQLAlchemy types.

Money is stored as TEXT holding the exact Decimal string representation, so no
binary floating-point error can corrupt the `balance <= threshold` comparison.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class DecimalString(TypeDecorator):
    """Store a Decimal as its canonical string; load it back as Decimal."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value)
