"""Coordinate local catalog loading and retain only mapped products."""

import re
from collections.abc import Sequence
from pathlib import Path

from app.adapters.catalog_downloader import DownloadedCatalog
from app.adapters.catalog_enrichment import load_enrichment
from app.adapters.catalog_loading import load_records
from app.adapters.catalog_mapping import map_product
from app.domain.catalog import Product
from app.domain.catalog_search import normalize_name


class ProductStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._products: dict[str, Product] = {}
        self._name_index: dict[str, tuple[str, ...]] = {}
        self.skipped = 0

    def local_files(self) -> DownloadedCatalog:
        return DownloadedCatalog(
            self._data_dir / "valio_products.json",
            self._data_dir / "valio_delivery_reliability.csv",
            self._data_dir / "valio_carbon_foot_print.csv",
        )

    def load(self, files: DownloadedCatalog) -> None:
        reliability = (
            load_enrichment(files.reliability, "deliveryReliability") if files.reliability else {}
        )
        carbon = load_enrichment(files.carbon, "AVG kg CO2-eq/kg") if files.carbon else {}
        products: dict[str, Product] = {}
        index: dict[str, list[str]] = {}
        skipped = 0
        records = load_records(files.products)
        for position, record in enumerate(records, 1):
            if not isinstance(record, dict):
                raise ValueError(f"{files.products}: record {position}: expected object")
            if record.get("deleted") is True:
                skipped += 1
                continue
            product_id = record.get("id")
            try:
                product = map_product(record, reliability.get(product_id), carbon.get(product_id))
                if product.product_id in products:
                    raise ValueError("duplicate product id")
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                raise ValueError(
                    f"{files.products}: record {position}, product {product_id!r}: {exc}"
                ) from exc
            products[product.product_id] = product
            words = {
                word
                for name in product.names.values()
                for word in re.findall(r"\w+", normalize_name(name))
            }
            for word in words:
                index.setdefault(word, []).append(product.product_id)
        self._products = products
        self._name_index = {name: tuple(ids) for name, ids in index.items()}
        self.skipped = skipped

    def search_names(self, query: str) -> Sequence[Product]:
        # Use the same tokens as the index; the service checks the full name afterwards.
        words = re.findall(r"\w+", normalize_name(query))
        if not words:
            return ()
        matched = [
            {pid for word, ids in self._name_index.items() if token in word for pid in ids}
            for token in words
        ]
        return tuple(self._products[pid] for pid in sorted(set.intersection(*matched)))

    def get(self, product_id: str) -> Product | None:
        return self._products.get(product_id)

    def products(self) -> Sequence[Product]:
        return tuple(self._products.values())

    def clear(self) -> None:
        self._products.clear()
        self._name_index.clear()
