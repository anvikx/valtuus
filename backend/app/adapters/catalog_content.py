"""Derive the content of an ordered sales unit."""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import Unit

_UNITS = {
    "MLT": (Unit.L, Decimal("0.001")),
    "CLT": (Unit.L, Decimal("0.01")),
    "LTR": (Unit.L, Decimal(1)),
    "GRM": (Unit.KG, Decimal("0.001")),
    "KGM": (Unit.KG, Decimal(1)),
    "ml": (Unit.L, Decimal("0.001")),
    "cl": (Unit.L, Decimal("0.01")),
    "l": (Unit.L, Decimal(1)),
    "g": (Unit.KG, Decimal("0.001")),
    "kg": (Unit.KG, Decimal(1)),
}
_NUMBER = r"\d+(?:[.,]\d+)?"
_UNIT = r"(?:kg|ml|cl|g|l)"
_FORWARD = re.compile(rf"(?<!\w)({_NUMBER})\s*[x\u00d7]\s*({_NUMBER})\s*({_UNIT})(?![a-z])", re.I)
_REVERSE = re.compile(rf"(?<!\w)({_NUMBER})\s*({_UNIT})\s*[x\u00d7]\s*({_NUMBER})(?!\w)", re.I)
_SINGLE = re.compile(rf"(?<!\w)({_NUMBER})\s*({_UNIT})(?![a-z])", re.I)


def _amount(value: object, unit: str, source: str) -> ContentPerSalesUnit | None:
    try:
        number = Decimal(str(value).replace(",", "."))
        target, factor = _UNITS[unit]
        if not number.is_finite() or number <= 0:
            return None
        return ContentPerSalesUnit(number * factor, target, source)
    except (InvalidOperation, KeyError, ValueError):
        return None


def _from_data(conversions: list[dict[str, Any]]) -> ContentPerSalesUnit | None:
    for conversion in conversions:
        for field in ("volume", "netWeight"):
            entry = conversion.get(field) or {}
            if isinstance(entry, dict):
                result = _amount(entry.get("value"), entry.get("unit"), "DATA")
                if result:
                    return result
    return None


def _from_names(names: list[str], multiplier: Decimal) -> ContentPerSalesUnit | None:
    for name in names:
        match = _FORWARD.search(name)
        if match:
            return _amount(
                Decimal(match[1].replace(",", ".")) * Decimal(match[2].replace(",", ".")),
                match[3].lower(),
                "NAME",
            )
        match = _REVERSE.search(name)
        if match:
            return _amount(
                Decimal(match[1].replace(",", ".")) * Decimal(match[3].replace(",", ".")),
                match[2].lower(),
                "NAME",
            )
    for name in names:
        matches = list(_SINGLE.finditer(name))
        if len(matches) == 1:
            match = matches[0]
            return _amount(
                Decimal(match[1].replace(",", ".")) * multiplier, match[2].lower(), "NAME"
            )
    return None


def map_content(record: dict[str, Any], names: list[str]) -> ContentPerSalesUnit | None:
    if record.get("salesUnit") == "KG":
        return ContentPerSalesUnit(Decimal(1), Unit.KG, "SALES_UNIT")
    synkka = record.get("synkkaData") or {}
    result = _from_data(synkka.get("unitConversions") or [])
    if result:
        return result
    multiplier = Decimal(1)
    for entry in record.get("units") or []:
        if entry.get("unitId") == record.get("salesUnit"):
            try:
                candidate = Decimal(str(entry.get("sizeInBaseUnits")))
                if candidate.is_finite() and candidate > 0:
                    multiplier = candidate
            except InvalidOperation:
                pass
            break
    return _from_names(names, multiplier)
