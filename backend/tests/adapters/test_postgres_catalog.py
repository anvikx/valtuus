"""Catalog replacement and name matching against a real test database."""

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.adapters.catalog_mapping import map_product
from app.adapters.postgres.catalog import PostgresCatalog
from app.adapters.postgres.tables import products


def _product(product_id, name):
    return map_product(
        {
            "id": product_id,
            "category": "1",
            "salesUnit": "KG",
            "allowedLotSize": Decimal("0.01"),
            "synkkaData": {"names": [{"language": "fi", "value": name}]},
        },
        Decimal("0.9999999999999999"),
        None,
    )


def test_catalog_search_and_atomic_replacement(database):
    catalog = PostgresCatalog(database)
    first = _product("1", "Ääni täysmaito UHT")
    second = _product("2", "Kaurajuoma")
    catalog.replace([first, second])

    assert catalog.get("1").content_per_sales_unit.value == first.content_per_sales_unit.value
    assert catalog.get("1").content_per_sales_unit.unit is None
    assert "body" not in products.c
    with database.reader() as connection:
        row = connection.execute(select(products).where(products.c.product_id == "1")).one()
    assert row.name == first.name
    assert row.lot_size == Decimal("0.01")
    assert row.names == {"fi": "Ääni täysmaito UHT"}
    assert catalog.get("1").delivery_reliability == Decimal("0.9999999999999999")
    assert [p.product_id for p in catalog.search_names("aani maito")] == ["1"]
    assert catalog.search_names("aani puuttuva") == []
    assert catalog.search_names("") == []

    with pytest.raises(IntegrityError):
        catalog.replace([first, first])
    assert {p.product_id for p in catalog.products()} == {"1", "2"}

    catalog.replace([second])
    assert catalog.get("1") is None
    assert catalog.get("2") is not None
