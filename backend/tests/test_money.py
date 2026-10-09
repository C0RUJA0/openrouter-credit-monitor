from decimal import Decimal

import pytest

from app.money import format_usd, parse_money, quantize_money, to_decimal


def test_to_decimal_from_float_is_exact():
    # 0.1 as float is imprecise; going through str keeps it clean.
    assert to_decimal(0.1) == Decimal("0.1")


def test_balance_subtraction_no_binary_error():
    total_credits = to_decimal("10.00")
    total_usage = to_decimal("0.10")
    assert total_credits - total_usage == Decimal("9.90")


def test_parse_money_accepts_comma_and_dot():
    assert parse_money("10,00") == Decimal("10.00")
    assert parse_money("10.5") == Decimal("10.50")
    assert parse_money("7") == Decimal("7.00")


def test_parse_money_rejects_invalid():
    with pytest.raises(ValueError):
        parse_money("abc")
    with pytest.raises(ValueError):
        parse_money("")
    with pytest.raises(ValueError):
        parse_money("-5")


def test_format_usd_comma_decimal():
    assert format_usd(Decimal("9.87")) == "US$ 9,87"
    assert format_usd(Decimal("32.5")) == "US$ 32,50"
    assert format_usd(None) == "US$ --"


def test_quantize_half_up():
    assert quantize_money(Decimal("9.875")) == Decimal("9.88")
