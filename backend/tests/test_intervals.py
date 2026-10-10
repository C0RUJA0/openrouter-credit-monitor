from app.intervals import to_seconds, split


def test_to_seconds():
    assert to_seconds(2, "min") == 120
    assert to_seconds(6, "h") == 21600
    assert to_seconds(1, "dias") == 86400
    assert to_seconds(1, "sem") == 604800
    assert to_seconds(1, "mes") == 2592000
    assert to_seconds(30, "seg") == 30
    assert to_seconds(5, "desconhecido") == 5  # fallback seconds


def test_split_picks_largest_unit():
    assert split(120) == (2, "min")
    assert split(21600) == (6, "h")
    assert split(86400) == (1, "dias")
    assert split(604800) == (1, "sem")
    assert split(300) == (5, "min")
    assert split(90) == (90, "seg")   # not a clean minute
    assert split(0) == (0, "seg")
