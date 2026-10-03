"""Input validation for checkout forms."""

import re

EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email))


def is_valid_pincode(pincode: str) -> bool:
    """Indian PIN codes: exactly 6 digits, first digit not 0."""
    return len(pincode) == 6 and pincode.isdigit() and pincode[0] != "0"


def normalize_phone(phone: str) -> str:
    """Keep digits only and drop a leading +91 / 91 country code -> 10-digit number."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) != 10:
        raise ValueError("phone number must have 10 digits")
    return digits


def is_strong_password(password: str) -> bool:
    """At least 8 characters with a digit, a lowercase and an uppercase letter."""
    return (
        len(password) >= 8
        and any(c.isdigit() for c in password)
        and any(c.islower() for c in password)
        and any(c.isupper() for c in password)
    )
