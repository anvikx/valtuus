from collections.abc import Sequence
from typing import Protocol

from app.domain.catalog import Product


class ProductCatalog(Protocol):
    """The product file, indexed in memory at startup. Deleted products are not in it."""

    def search_names(self, query: str) -> Sequence[Product]: ...

    def get(self, product_id: str) -> Product | None: ...

    def products(self) -> Sequence[Product]: ...
