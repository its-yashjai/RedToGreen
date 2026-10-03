import pytest

from shopkit.stats import clamp, mean, median, percent_change, top_n


def test_mean():
    assert mean([1, 2, 3, 4]) == 2.5
    with pytest.raises(ValueError):
        mean([])


def test_median_odd_and_even():
    assert median([5, 1, 3]) == 3
    assert median([4, 1, 3, 2]) == 2.5


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-3, 0, 10) == 0
    assert clamp(42, 0, 10) == 10


def test_percent_change():
    assert percent_change(100, 120) == 20.0
    assert percent_change(200, 150) == -25.0
    with pytest.raises(ValueError):
        percent_change(0, 10)


def test_top_n():
    sales = {"case": 50, "cable": 120, "charger": 80}
    assert top_n(sales, 2) == ["cable", "charger"]
