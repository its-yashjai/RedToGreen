import pytest

from shopkit.dates import days_in_month, delivery_days, is_leap_year


def test_leap_years():
    assert is_leap_year(2024)
    assert is_leap_year(2000)
    assert not is_leap_year(1900)
    assert not is_leap_year(2023)


def test_days_in_month():
    assert days_in_month(2024, 2) == 29
    assert days_in_month(2023, 2) == 28
    assert days_in_month(2023, 12) == 31
    assert days_in_month(2023, 4) == 30
    with pytest.raises(ValueError):
        days_in_month(2023, 13)


def test_delivery_days():
    assert delivery_days(10) == 1
    assert delivery_days(50) == 1
    assert delivery_days(51) == 2
    assert delivery_days(350) == 2
    assert delivery_days(351) == 3
