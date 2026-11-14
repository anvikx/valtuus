"""Load the product source with exact decimal values."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any


def load_records(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8-sig") as source:
            data = json.load(source, parse_float=Decimal)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: cannot load products: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected an array of products")
    return data
