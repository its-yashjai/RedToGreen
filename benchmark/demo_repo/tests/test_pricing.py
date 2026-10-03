import pytest

from shopkit.pricing import (
    add_gst,
    apply_discount,
    bulk_unit_price,
    final_price,
    round_money,
    shipping_cost,
)


def test_round_money():
    assert round_money(10.456) == 10.46
    assert round_money(3) == 3


def test_apply_discount():
    assert apply_discount(200, 10) == 180
    assert apply_discount(999, 0) == 999
    assert apply_discount(500, 100) == 0


def test_apply_discount_rejects_bad_percent():
    with pytest.raises(ValueError):
        apply_discount(100, 120)
    with pytest.raises(ValueError):
        apply_discount(100, -5)


def test_add_gst():
    assert add_gst(100) == 118
    assert add_gst(100, rate=0.05) == 105


def test_shipping_cost():
    assert shipping_cost(100) == 40
    assert shipping_cost(499) == 0
    assert shipping_cost(1200) == 0


def test_bulk_unit_price():
    assert bulk_unit_price(100, 1) == 100
    assert bulk_unit_price(100, 10) == 95
    assert bulk_unit_price(100, 49) == 95
    assert bulk_unit_price(100, 50) == 90


def test_final_price():
    assert final_price(100) == 158.0          # 118 tax-incl + 40 shipping
    assert final_price(1000, 10) == 1062.0    # 900 -> 1062, free shipping
    assert final_price(450) == 571.0          # shipping is decided before tax: 531 + 40
