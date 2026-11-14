from collections.abc import Sequence
from pathlib import Path

from app.domain.catalog import Product


class ProductStore:
    """The challenge product file, indexed in memory.

    Loads nothing at construction: CI has no challenge data, so the app must start without it.
    """

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def get(self, product_id: str) -> Product | None:
        raise NotImplementedError("ProductStore.get")

    def products(self) -> Sequence[Product]:
        raise NotImplementedError("ProductStore.products")
