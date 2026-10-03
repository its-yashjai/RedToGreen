"""Prices, discounts and tax. All money values are in rupees."""

GST_RATE = 0.18
FREE_SHIPPING_ABOVE = 499
SHIPPING_FEE = 40


def round_money(amount: float) -> float:
    """Round to 2 decimal places."""
    return round(amount, 2)


def apply_discount(price: float, percent: float) -> float:
    """Price after a percentage discount. percent must be between 0 and 100."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round_money(price - price * percent / 100)


def add_gst(amount: float, rate: float = GST_RATE) -> float:
    """Amount including GST."""
    return round_money(amount * (1 + rate))


def shipping_cost(order_total: float) -> float:
    """Shipping is free when the order total is at least FREE_SHIPPING_ABOVE."""
    if order_total >= FREE_SHIPPING_ABOVE:
        return 0
    return SHIPPING_FEE


def bulk_unit_price(unit_price: float, quantity: int) -> float:
    """Tiered bulk discount: 10+ items get 5% off, 50+ items get 10% off."""
    if quantity >= 50:
        return apply_discount(unit_price, 10)
    if quantity >= 10:
        return apply_discount(unit_price, 5)
    return unit_price


def final_price(subtotal: float, coupon_percent: float = 0) -> float:
    """Subtotal -> coupon -> GST -> shipping."""
    discounted = apply_discount(subtotal, coupon_percent)
    with_tax = add_gst(discounted)
    return round_money(with_tax + shipping_cost(discounted))
