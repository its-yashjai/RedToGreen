import pytest

from shopkit.cart import Cart


def make_cart():
    cart = Cart()
    cart.add("case", 299, 2)
    cart.add("cable", 149)
    return cart


def test_add_and_total():
    assert make_cart().total() == 747


def test_add_same_sku_merges():
    cart = make_cart()
    cart.add("case", 299)
    assert cart.items["case"].quantity == 3
    assert len(cart.items) == 2


def test_add_rejects_zero_quantity():
    with pytest.raises(ValueError):
        Cart().add("case", 299, 0)


def test_remove_partial_and_full():
    cart = make_cart()
    cart.remove("case")
    assert cart.items["case"].quantity == 1
    cart.remove("case")
    assert "case" not in cart.items


def test_remove_missing_raises():
    with pytest.raises(KeyError):
        Cart().remove("ghost")


def test_item_count():
    assert make_cart().item_count() == 3


def test_is_empty():
    assert Cart().is_empty()
    assert not make_cart().is_empty()


def test_most_expensive():
    assert make_cart().most_expensive().sku == "case"
    assert Cart().most_expensive() is None
