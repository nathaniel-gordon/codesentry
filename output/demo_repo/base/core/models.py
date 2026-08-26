"""Domain models for warehouse stock."""
from dataclasses import dataclass, field


@dataclass
class StockItem:
    """A single SKU held in one warehouse."""

    sku: str
    quantity: int
    reserved: int = 0

    def available(self) -> int:
        """Return the quantity that can still be promised to customers."""
        return max(self.quantity - self.reserved, 0)


@dataclass
class Warehouse:
    """A named warehouse holding a set of stock items."""

    name: str
    items: list = field(default_factory=list)

    def total_available(self) -> int:
        """Return the promisable quantity across every stocked item."""
        return sum(item.available() for item in self.items)

    def find(self, sku):
        """Return the item with this SKU, or None when it is not stocked."""
        for item in self.items:
            if item.sku == sku:
                return item
        return None
