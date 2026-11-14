"""Piece counts use the catalog's H87 code or explicit en/fi/sv name units."""

from decimal import Decimal

import pytest

from app.adapters.catalog_content import map_content
from app.domain.enums import Unit


@pytest.mark.parametrize("code", ["H87", "PCS", "PCE"])
def test_structured_piece_content_precedes_net_weight(code):
    source = {
        "salesUnit": "ST",
        "synkkaData": {
            "unitConversions": [
                {
                    "volume": {"unit": code, "value": Decimal(50)},
                    "netWeight": {"unit": "GRM", "value": Decimal(219)},
                }
            ]
        },
    }

    content = map_content(source, ["PikPak 50pcs 20L waste bag"])

    assert (content.value, content.unit, content.source) == (Decimal(50), Unit.PCS, "DATA")


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Toothbrush 1 PC", 1),
        ("Hammasharja 1 kpl", 1),
        ("Näsduk 75 st", 75),
        ("Napkin 40pcs", 40),
        ("2 x 50 pcs", 100),
        ("50 pcs x 2", 100),
        ("2 \u00d7 50 kpl", 100),
        ("5 pieces", 5),
        ("1 piece", 1),
    ],
)
def test_piece_names_and_multipacks(name, expected):
    content = map_content({"salesUnit": "PAK"}, [name])

    assert (content.value, content.unit, content.source) == (Decimal(expected), Unit.PCS, "NAME")


def test_name_count_uses_sales_unit_multiplier_once():
    source = {"salesUnit": "KI", "units": [{"unitId": "KI", "sizeInBaseUnits": Decimal(18)}]}

    content = map_content(source, ["LOTUS Nessu Sensitive Hankie 75 pcs"])
    multipack = map_content(source, ["18 x 75 pcs"])

    assert content.value == multipack.value == Decimal(1350)
    assert content.unit == multipack.unit == Unit.PCS


@pytest.mark.parametrize("amount", [None, 0, -1, "NaN", "Infinity", "bad"])
def test_invalid_piece_data_does_not_become_known_content(amount):
    source = {"synkkaData": {"unitConversions": [{"volume": {"unit": "H87", "value": amount}}]}}

    assert map_content(source, ["Unknown product"]) is None


def test_physical_content_priority_is_preserved():
    structured = {
        "salesUnit": "ST",
        "synkkaData": {
            "unitConversions": [
                {
                    "volume": {"unit": "LTR", "value": Decimal(1)},
                }
            ]
        },
    }

    assert map_content(structured, ["Milk 1 l 6 pcs"]).unit == Unit.L
    assert map_content({"salesUnit": "KG"}, ["Jackfruit 1 pcs"]).unit == Unit.KG
    assert map_content({}, ["Candy 170g x14 pcs"]).unit == Unit.KG
    assert map_content({}, ["1 ST"]).unit == Unit.PCS
    assert map_content({}, ["ST.DALFOUR jam"]) is None
