"""Read optional catalog enrichment without losing decimal precision."""

import csv
import logging
from decimal import Decimal, InvalidOperation
from pathlib import Path

_LOG = logging.getLogger(__name__)


def load_enrichment(path: Path, value_column: str) -> dict[str, Decimal]:
    if not path.exists():
        return {}

    values: dict[str, Decimal] = {}
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or not {"productId", value_column} <= set(reader.fieldnames):
            _LOG.warning("%s: missing productId or %s column", path, value_column)
            return values

        for line, row in enumerate(reader, start=2):
            product_id = (row.get("productId") or "").strip()
            raw = (row.get(value_column) or "").strip()
            if not product_id:
                _LOG.warning("%s:%s: missing productId", path, line)
                continue
            if not raw:
                continue
            try:
                value = Decimal(raw)
                if not value.is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                _LOG.warning(
                    "%s:%s: invalid %s for product %s", path, line, value_column, product_id
                )
                continue
            values[product_id] = value
    return values
