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
    assert row.name == "Ääni täysmaito UHT"
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


def test_multilingual_search_and_allergen_round_trip(database):
    from tests.adapters.test_product_store import record

    source = record()
    source["allowedLotSize"] = Decimal("0.01")
    source["synkkaData"]["classifications"] = [
        {
            "name": "allergen",
            "values": [
                {"id": "milk", "unit": "CONTAINS"},
                {"id": "nuts", "unit": "MAY_CONTAIN"},
            ],
        }
    ]
    product = map_product(source, None, None)
    catalog = PostgresCatalog(database)

    catalog.replace([product])

    for query in ("milk", "maito", "mjölk", "mjolk", "milk maito mjolk"):
        assert [item.product_id for item in catalog.search_names(query)] == ["1"]
    stored = catalog.get("1")
    assert stored.name == "Milk UHT 1 l"
    assert stored.allergens == product.allergens
    with database.reader() as connection:
        row = connection.execute(select(products)).one()
    assert row.allergen == {"CONTAINS": ["milk"], "MAY_CONTAIN": ["nuts"]}
    assert row.search_names == "milk uht 1 l maito 1 l mjolk 1 l"


def test_allergen_migration_preserves_codes_and_search_index(database):
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    migration = import_module(
        "app.adapters.postgres.migrations.versions.0006_allergen_declarations"
    )
    catalog = PostgresCatalog(database)
    catalog.replace([_product("1", "Maito"), _product("2", "Kaura")])

    with database.transaction():
        connection = database.writer()
        # Shadow only products so the test exercises the old type without changing the schema.
        connection.execute(
            text("CREATE TEMP TABLE products ON COMMIT DROP AS SELECT * FROM products")
        )
        connection.execute(
            text(
                "ALTER TABLE products ALTER COLUMN allergen TYPE text[] "
                "USING CASE WHEN product_id = '1' THEN ARRAY['milk', 'nuts'] "
                "ELSE ARRAY[]::text[] END"
            )
        )
        connection.execute(text("UPDATE products SET allergen_status = 'KNOWN'"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        rows = (
            connection.execute(
                text(
                    "SELECT product_id, name, search_names, allergen, allergen_status "
                    "FROM products ORDER BY product_id"
                )
            )
            .mappings()
            .all()
        )
        index = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_products_search_names_trgm'"
            )
        ).scalar_one()

    assert rows[0]["allergen"] == {"CONTAINS": ["milk", "nuts"], "MAY_CONTAIN": []}
    assert rows[1]["allergen"] == {"CONTAINS": [], "MAY_CONTAIN": []}
    assert all(row["allergen_status"] == "UNKNOWN" for row in rows)
    assert rows[0]["name"] == "Maito"
    assert rows[0]["search_names"] == "maito"
    assert "USING gin (search_names gin_trgm_ops)" in index
