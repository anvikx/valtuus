import json
from decimal import Decimal

import pytest

from app.adapters.catalog_allergens import map_allergens
from app.adapters.catalog_content import map_content
from app.adapters.catalog_downloader import DownloadedCatalog
from app.adapters.product_store import ProductStore, normalize_name
from app.domain.enums import AllergenStatus, Unit

load_catalog = ProductStore.load


def record(product_id="1"):
    return {
        "id": product_id,
        "category": "1",
        "salesUnit": "KI",
        "allowedLotSize": 0.01,
        "units": [{"unitId": "KI", "sizeInBaseUnits": 5}],
        "synkkaData": {
            "names": [
                {"language": "fi", "value": "Maito 1 l"},
                {"language": "en", "value": "Milk UHT 1 l"},
            ],
            "brand": " Brand ",
            "classifications": [],
        },
    }


@pytest.mark.parametrize(
    ("sales", "name", "conversion", "size", "expected", "unit", "source"),
    [
        ("KG", "pumpkin", None, 1, "1", Unit.KG, "SALES_UNIT"),
        ("KI", "5 x 1 l", {"volume": {"value": 5, "unit": "LTR"}}, 5, "5", Unit.L, "DATA"),
        (
            "KI",
            "60 x 100 g",
            {"netWeight": {"value": 6000, "unit": "GRM"}},
            60,
            "6",
            Unit.KG,
            "DATA",
        ),
        ("KI", "200gx18", None, 1, "3.6", Unit.KG, "NAME"),
        ("KI", "1 l", None, 5, "5", Unit.L, "NAME"),
        ("KI", "10 l", None, 2, "20", Unit.L, "NAME"),
    ],
)
def test_content_examples(sales, name, conversion, size, expected, unit, source):
    item = {
        "salesUnit": sales,
        "units": [{"unitId": sales, "sizeInBaseUnits": size}],
        "synkkaData": {"unitConversions": [conversion] if conversion else []},
    }
    result = map_content(item, [name])
    assert (result.value, result.unit, result.source) == (Decimal(expected), unit, source)


def test_allergen_unknown_and_may_contain():
    result = map_allergens(
        [
            {
                "name": "allergen",
                "values": [{"id": "A", "unit": "MAY_CONTAIN"}, {"id": "B", "unit": "UNDECLARED"}],
            }
        ]
    )
    assert result.contains == ("A",)
    assert result.status == AllergenStatus.UNKNOWN


def test_load_maps_enrichment_and_names(tmp_path):
    path = tmp_path / "products.json"
    path.write_text(json.dumps([record(), {"deleted": True}]))
    csv = tmp_path / "reliability.csv"
    csv.write_text("productId,deliveryReliability\n1,0.1234567890123456789\n")
    store = ProductStore(tmp_path)
    load_catalog(store, DownloadedCatalog(path, csv, None))
    product = store.get("1")
    assert product.name == "Milk UHT 1 l"
    assert product.names == {"en": "Milk UHT 1 l"}
    assert product.brand == "Brand"
    assert product.delivery_reliability == Decimal("0.1234567890123456789")
    assert product.co2_kg_per_kg is None
    assert product.content_per_sales_unit.value == Decimal(5)
    assert "UHT" in product.attributes
    assert store.skipped == 1
    assert normalize_name("Ääni") == "aani"


def test_duplicate_id_has_context(tmp_path):
    path = tmp_path / "products.json"
    path.write_text(json.dumps([record(), record()]))
    store = ProductStore(tmp_path)
    with pytest.raises(ValueError, match=r"record 2.*duplicate product id"):
        load_catalog(store, DownloadedCatalog(path, None, None))
