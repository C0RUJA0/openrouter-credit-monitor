"""Money helpers. All monetary values are Decimal, never float."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

TWO_PLACES = Decimal("0.01")


def to_decimal(value) -> Decimal:
    """Coerce an arbitrary numeric/string value into Decimal via its string form.

    Going through str() avoids importing binary float imprecision.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    return Decimal(str(value))


def quantize_money(value: Decimal) -> Decimal:
    return to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def parse_money(raw: str) -> Decimal:
    """Parse user input. Accepts '10', '10.00', '10,00'. Raises ValueError if invalid."""
    if raw is None:
        raise ValueError("empty value")
    cleaned = str(raw).strip().replace(" ", "")
    if cleaned == "":
        raise ValueError("empty value")
    # Accept comma as decimal separator.
    cleaned = cleaned.replace(",", ".")
    try:
        value = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise ValueError(f"invalid monetary value: {raw!r}")
    if value < 0:
        raise ValueError("value must not be negative")
    return quantize_money(value)


def format_usd(value: Decimal | None) -> str:
    """Format as 'US$ 9,87' (comma decimal separator), or 'US$ --' when unknown."""
    if value is None:
        return "US$ --"
    q = quantize_money(value)
    return "US$ " + f"{q:.2f}".replace(".", ",")
