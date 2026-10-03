"""Small statistics helpers for the sales dashboard."""


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of empty list")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("median of empty list")
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def percent_change(old: float, new: float) -> float:
    """Percentage change from old to new, e.g. 100 -> 120 is 20.0"""
    if old == 0:
        raise ValueError("old value must not be zero")
    return round((new - old) / old * 100, 2)


def top_n(sales: dict[str, float], n: int) -> list[str]:
    """Names of the n best sellers, highest first."""
    return [name for name, _ in sorted(sales.items(), key=lambda kv: kv[1], reverse=True)[:n]]
