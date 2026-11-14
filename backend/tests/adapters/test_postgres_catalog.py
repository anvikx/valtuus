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
    assert row.allergen == ["milk", "nuts"]
    assert row.allergen_declarations == {"CONTAINS": ["milk"], "MAY_CONTAIN": ["nuts"]}
    assert stored.names == product.names
    assert row.search_names == "milk uht 1 l maito 1 l mjolk 1 l"


def test_allergen_migration_preserves_codes_and_search_index(database):
    from importlib import import_module

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    migration = import_module(
        "app.adapters.postgres.migrations.versions.0008_allergen_declarations"
    )
    catalog = PostgresCatalog(database)
    catalog.replace([_product("1", "Maito"), _product("2", "Kaura")])

    with database.transaction():
        connection = database.writer()
        # Shadow only products so the test exercises the old type without changing the schema.
        connection.execute(
            text("CREATE TEMP TABLE products ON COMMIT DROP AS SELECT * FROM products")
        )
        connection.execute(text("ALTER TABLE products DROP COLUMN allergen_declarations"))
        connection.execute(text("ALTER TABLE products DROP COLUMN names"))
        connection.execute(
            text("UPDATE products SET allergen = ARRAY['milk', 'nuts'], allergen_status = 'KNOWN'")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        rows = (
            connection.execute(
                text(
                    "SELECT product_id, name, search_names, allergen, allergen_status, "
                    "allergen_declarations, names "
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

    assert all(row["allergen"] == ["milk", "nuts"] for row in rows)
    assert all(row["allergen_status"] == "KNOWN" for row in rows)
    assert all(row["allergen_declarations"] is None and row["names"] is None for row in rows)
    assert rows[0]["name"] == "Maito"
    assert rows[0]["search_names"] == "maito"
    assert "USING gin (search_names gin_trgm_ops)" in index


@pytest.mark.parametrize("kind", ["FREE_FROM", "CONTAINS", "MAY_CONTAIN"])
def test_known_declarations_and_names_survive_storage(database, kind):
    """Persistence must preserve known absence as well as positive declaration types."""
    from dataclasses import replace

    from app.adapters.catalog_allergens import map_allergens
    from app.domain.enums import AllergenStatus

    product = replace(
        _product("1", "Maito"),
        allergens=map_allergens([{"name": "allergen", "values": [{"id": "milk", "unit": kind}]}]),
    )
    catalog = PostgresCatalog(database)

    catalog.replace([product])

    stored = catalog.get("1")
    assert stored.allergens == product.allergens
    assert stored.allergens.status == AllergenStatus.KNOWN
    assert stored.names == {"fi": "Maito"}


def test_legacy_writer_on_new_schema(database):
    """An old image can replace products without writing either added column."""
    from sqlalchemy import insert

    from app.domain.enums import AllergenStatus

    catalog = PostgresCatalog(database)
    catalog.replace([_product("1", "Maito")])
    with database.transaction():
        connection = database.writer()
        legacy = dict(connection.execute(select(products)).mappings().one())
        legacy.pop("allergen_declarations")
        legacy.pop("names")
        legacy.update(product_id="2", allergen=["nuts"], allergen_status="KNOWN")
        connection.execute(insert(products), legacy)

    stored = catalog.get("2")
    assert stored.allergens.contains == ("nuts",)
    assert stored.allergens.status == AllergenStatus.KNOWN
    assert stored.names == {}
    assert stored.name == "Maito"
