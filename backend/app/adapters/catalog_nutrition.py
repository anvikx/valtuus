"""Normalize declared nutrients to grams per 100 g or 100 ml."""

from decimal import Decimal, InvalidOperation
from typing import Any

_GRAMS = {"GRM": Decimal(1), "KGM": Decimal(1000)}
_BASES = {
    "GRM": Decimal(1),
    "KGM": Decimal(1000),
    "MLT": Decimal(1),
    "CLT": Decimal(10),
    "LTR": Decimal(1000),
}


def map_nutrients(entries: list[dict[str, Any]]) -> dict[str, Decimal]:
    nutrients: dict[str, Decimal] = {}
    bases: dict[str, Decimal] = {}
    for entry in entries:
        code = entry.get("id")
        if code not in ("FAT", "SUGAR-", "PRO-"):
            continue
        try:
            value = Decimal(str(entry.get("value"))) * _GRAMS[entry.get("unit")]
            basis = (
                Decimal(str(entry.get("basisQuantity"))) * _BASES[entry.get("basisQuantityUnit")]
            )
            if not value.is_finite() or not basis.is_finite() or value < 0 or basis <= 0:
                continue
            if code not in nutrients or (basis == 100 and bases[code] != 100):
                nutrients[code] = value * Decimal(100) / basis
                bases[code] = basis
        except (InvalidOperation, KeyError, ValueError):
            continue
    return nutrients
