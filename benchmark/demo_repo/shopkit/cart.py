"""A shopping cart."""

from dataclasses import dataclass, field


@dataclass
class Item:
    sku: str
    price: float
    quantity: int = 1


@dataclass
class Cart:
    items: dict[str, Item] = field(default_factory=dict)

    def add(self, sku: str, price: float, quantity: int = 1) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if sku in self.items:
            self.items[sku].quantity += quantity
        else:
            self.items[sku] = Item(sku, price, quantity)

    def remove(self, sku: str, quantity: int = 1) -> None:
        item = self.items.get(sku)
        if item is None:
            raise KeyError(sku)
        item.quantity -= quantity
        if item.quantity <= 0:
            del self.items[sku]

    def total(self) -> float:
        return round(sum(i.price * i.quantity for i in self.items.values()), 2)

    def item_count(self) -> int:
        return sum(i.quantity for i in self.items.values())

    def is_empty(self) -> bool:
        return len(self.items) == 0

    def most_expensive(self) -> Item | None:
        if not self.items:
            return None
        return max(self.items.values(), key=lambda i: i.price)
