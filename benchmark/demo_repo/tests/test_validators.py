import pytest

from shopkit.validators import is_strong_password, is_valid_email, is_valid_pincode, normalize_phone


def test_valid_emails():
    assert is_valid_email("ravi@example.com")
    assert is_valid_email("a.b+shop@mail.co.in")


def test_invalid_emails():
    assert not is_valid_email("ravi@")
    assert not is_valid_email("ravi.example.com")
    assert not is_valid_email("ravi@example")


def test_pincode():
    assert is_valid_pincode("560037")
    assert not is_valid_pincode("056003")
    assert not is_valid_pincode("56003")
    assert not is_valid_pincode("5600a7")


def test_normalize_phone():
    assert normalize_phone("+91 98765 43210") == "9876543210"
    assert normalize_phone("9876543210") == "9876543210"
    with pytest.raises(ValueError):
        normalize_phone("12345")


def test_strong_password():
    assert is_strong_password("Secure123")
    assert is_strong_password("Abcdef12")  # exactly 8 characters is enough
    assert not is_strong_password("short1A")
    assert not is_strong_password("alllowercase1")
    assert not is_strong_password("NoDigitsHere")
