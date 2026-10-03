"""Delivery date helpers (no external libraries)."""

DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(year: int, month: int) -> int:
    if not 1 <= month <= 12:
        raise ValueError("month must be 1-12")
    if month == 2 and is_leap_year(year):
        return 29
    return DAYS_IN_MONTH[month - 1]


def delivery_days(distance_km: float) -> int:
    """1 day within 50 km, then 1 extra day per started 300 km."""
    if distance_km <= 50:
        return 1
    extra = int((distance_km - 50 + 299) // 300)
    return 1 + extra
