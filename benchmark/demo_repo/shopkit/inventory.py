"""Stock levels."""


class OutOfStock(Exception):
    pass


class Inventory:
    def __init__(self) -> None:
        self.stock: dict[str, int] = {}

    def restock(self, sku: str, amount: int) -> None:
        if amount <= 0:
            raise ValueError("amount must be positive")
        self.stock[sku] = self.stock.get(sku, 0) + amount

    def in_stock(self, sku: str, amount: int = 1) -> bool:
        return self.stock.get(sku, 0) >= amount

    def reserve(self, sku: str, amount: int) -> None:
        if not self.in_stock(sku, amount):
            raise OutOfStock(sku)
        self.stock[sku] -= amount

    def low_stock(self, threshold: int = 5) -> list[str]:
        """SKUs with fewer than `threshold` units, sorted alphabetically."""
        return sorted(sku for sku, qty in self.stock.items() if qty < threshold)
