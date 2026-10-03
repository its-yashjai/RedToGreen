import pytest

from shopkit.inventory import Inventory, OutOfStock


def stocked():
    inv = Inventory()
    inv.restock("case", 10)
    inv.restock("cable", 3)
    return inv


def test_restock_adds_up():
    inv = stocked()
    inv.restock("case", 5)
    assert inv.stock["case"] == 15


def test_restock_rejects_non_positive():
    with pytest.raises(ValueError):
        Inventory().restock("case", 0)


def test_in_stock_boundary():
    inv = stocked()
    assert inv.in_stock("cable", 3)
    assert not inv.in_stock("cable", 4)
    assert not inv.in_stock("ghost")


def test_reserve():
    inv = stocked()
    inv.reserve("case", 4)
    assert inv.stock["case"] == 6


def test_reserve_too_many():
    with pytest.raises(OutOfStock):
        stocked().reserve("cable", 5)


def test_low_stock():
    inv = stocked()
    inv.restock("charger", 5)
    assert inv.low_stock() == ["cable"]
    assert inv.low_stock(threshold=11) == ["cable", "case", "charger"]
