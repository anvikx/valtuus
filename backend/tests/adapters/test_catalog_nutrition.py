from decimal import Decimal

from app.adapters.catalog_nutrition import map_nutrients


def nutrient(value, basis, basis_unit="GRM", unit="GRM"):
    return {
        "id": "FAT",
        "value": value,
        "unit": unit,
        "basisQuantity": basis,
        "basisQuantityUnit": basis_unit,
    }


def test_normalizes_serving_and_prefers_explicit_per_100():
    assert map_nutrients([nutrient(Decimal("4.5"), 30)]) == {"FAT": Decimal(15)}
    assert map_nutrients([nutrient(Decimal("4.5"), 30), nutrient(Decimal("14.9"), 100)]) == {
        "FAT": Decimal("14.9")
    }
    assert map_nutrients([nutrient(Decimal("14.9"), 100), nutrient(Decimal("4.5"), 30)]) == {
        "FAT": Decimal("14.9")
    }


def test_refuses_unknown_basis_and_invalid_units():
    assert map_nutrients([nutrient(4, 1, "PTN")]) == {}
    assert map_nutrients([nutrient(4, 100, unit="KJO")]) == {}
    assert map_nutrients([nutrient(4, 0)]) == {}


def test_normalizes_kilograms_and_liquid_basis():
    assert map_nutrients([nutrient(40, 1, "KGM")]) == {"FAT": Decimal(4)}
    assert map_nutrients([nutrient(Decimal("0.004"), 10, "CLT", "KGM")]) == {"FAT": Decimal(4)}
