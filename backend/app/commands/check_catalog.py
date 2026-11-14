"""Inspect downloaded catalog files without contacting Valio."""

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from app.adapters.product_store import ProductStore
from app.config import Settings
from app.domain.enums import AllergenStatus


def _write(value: str) -> None:
    sys.stdout.write(value + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("product_id", nargs="?")
    parser.add_argument("--data-dir", type=Path, default=Settings().data_dir)
    args = parser.parse_args()
    start = time.perf_counter()
    store = ProductStore(args.data_dir)
    try:
        store.load(store.local_files())
    except ValueError as exc:
        sys.stderr.write(f"Validation error: {exc}\n")
        return 1
    products = store.products()
    coverage = Counter(
        product.content_per_sales_unit.source if product.content_per_sales_unit else "unknown"
        for product in products
    )
    _write(f"Products: {len(products)}; skipped: {store.skipped}")
    _write(f"Reliability coverage: {sum(p.delivery_reliability is not None for p in products)}")
    _write(f"Carbon coverage: {sum(p.co2_kg_per_kg is not None for p in products)}")
    _write(f"Content sources: {dict(coverage)}")
    _write(
        f"Unknown allergens: {sum(p.allergens.status == AllergenStatus.UNKNOWN for p in products)}"
    )
    _write(f"Parsing and indexing: {time.perf_counter() - start:.3f}s")
    if args.product_id:
        product = store.get(args.product_id)
        if product is None:
            sys.stderr.write(f"Product not found: {args.product_id}\n")
            return 1
        _write(json.dumps(asdict(product), default=str, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
