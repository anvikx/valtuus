"""S2 category visibility, hint priority and audit completeness."""

from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from app.domain.catalog import Allergens, ContentPerSalesUnit
from app.domain.enums import AllergenStatus, Decision, Unit
from tests.adapters.samples import agent_key
from tests.fakes.offer_data import FakeCatalog
from tests.services.test_catalog_service import item, query, service

_SENTENCES = {
    "EXCLUDED_ONLY": "Products match, but the buyer's rules remove all of them. Tell the buyer.",
    "NO_MATCH": "No product matches. Try other words, or fewer words.",
    "MISSING_FIELDS": "Ask the buyer for the missing values before the offers.",
    "GUARD_CUT": "The list is not complete. Add an attribute, a unit or more words.",
    "READY": "The list has every product of this type. Call get_offers with all candidates.",
}


@pytest.mark.parametrize(
    "hits,excluded,missing,expected",
    [
        pytest.param(0, 0, (), "NO_MATCH", id="no-match"),
        pytest.param(0, 1, (), "EXCLUDED_ONLY", id="excluded-only"),
        pytest.param(0, 0, ("quantity",), "NO_MATCH", id="no-match-before-missing"),
        pytest.param(0, 1, ("quantity",), "EXCLUDED_ONLY", id="excluded-before-missing"),
        pytest.param(1, 0, ("quantity",), "MISSING_FIELDS", id="missing-quantity"),
        pytest.param(1, 0, ("unit",), "MISSING_FIELDS", id="missing-unit"),
        pytest.param(1, 0, ("deliver_by",), "MISSING_FIELDS", id="missing-date"),
        pytest.param(1, 0, ("quantity", "unit", "deliver_by"), "MISSING_FIELDS", id="missing-all"),
        pytest.param(3, 0, (), "GUARD_CUT", id="guard-cut"),
        pytest.param(3, 0, ("quantity",), "MISSING_FIELDS", id="missing-before-guard"),
        pytest.param(1, 0, (), "READY", id="ready"),
    ],
)
def test_hint_priority(hits, excluded, missing, expected):
    products = [item(f"hit-{i}") for i in range(hits)] + [
        item(f"excluded-{i}", allergens=Allergens(AllergenStatus.UNKNOWN, ()))
        for i in range(excluded)
    ]
    catalog, records = service(
        FakeCatalog(*products),
        candidate_guard=2,
        allergen_unknown_policy=Decision.DENY,
    )

    result = catalog.search(agent_key(), query(**dict.fromkeys(missing)))

    assert result.hint.code == expected
    assert result.hint.sentence == _SENTENCES[expected]
    assert result.missing_fields == missing
    assert result.total_hits == hits
    assert len(records.records) == 1
    audit = records.records[0]
    assert audit.request_id == result.request_id
    assert audit.buyer_id == agent_key().buyer_id
    assert audit.phase == "LOOKUP"
    assert audit.input_data == asdict(result.understood)
    assert audit.output_data == {
        "candidate_ids": [p.product_id for p in result.candidates],
        "hint_category": result.hint_category,
        "total_hits": hits,
        "hint": asdict(result.hint),
    }


def test_top_eight_counts_all_categories_and_deduplicates_examples():
    products = [
        item("1", "Milk", category="10"),
        item("2", "Milk", category="10"),
        item("3", "Fresh milk", category="10"),
        item("4", "Other milk", category="10"),
    ]
    products += [item(f"cat-{code}", category=str(code)) for code in range(1, 11) if code != 10]
    catalog, _ = service(FakeCatalog(*reversed(products)))

    result = catalog.search(agent_key(), query())

    assert result.total_hits == 13
    assert [s.category for s in result.categories] == ["10", "1", "2", "3", "4", "5", "6", "7"]
    assert result.categories[0].hits == 4
    assert result.categories[0].examples == ("Milk", "Fresh milk")
    assert all(len(summary.examples) == 1 for summary in result.categories[1:])
    assert result.hint_category == "10"
    assert {p.product_id for p in result.candidates} == {"1", "2", "3", "4"}


def test_guard_preserves_total_and_category_counts_at_boundary():
    catalog, _ = service(FakeCatalog(*(item(str(i)) for i in range(501))))

    cut = catalog.search(agent_key(), query())

    assert len(cut.candidates) == 500
    assert cut.total_hits == cut.categories[0].hits == 501
    assert cut.hint.code == "GUARD_CUT"
    catalog, _ = service(FakeCatalog(*(item(str(i)) for i in range(500))))
    complete = catalog.search(agent_key(), query())
    assert len(complete.candidates) == complete.total_hits == 500
    assert complete.hint.code == "READY"


def test_filters_define_totals_and_explicit_category_summary():
    products = [
        item("1", category="1", attributes=("FREE_FROM_LACTOSE",)),
        item("2", category="2", attributes=("FREE_FROM_LACTOSE",)),
        item("no-attribute", category="1"),
        item(
            "kg",
            category="1",
            attributes=("FREE_FROM_LACTOSE",),
            content_per_sales_unit=ContentPerSalesUnit(Decimal(1), Unit.KG),
        ),
    ]
    catalog, _ = service(FakeCatalog(*products))

    result = catalog.search(
        agent_key(), query(category="1", required_attributes=("FREE_FROM_LACTOSE",))
    )

    assert result.total_hits == 1
    assert [s.category for s in result.categories] == ["1"]
    assert result.categories[0].hits == 1
    assert [p.product_id for p in result.candidates] == ["1"]
    empty = catalog.search(agent_key(), query(category="missing"))
    assert empty.hint_category == "missing"
    assert empty.total_hits == 0
    assert empty.categories == ()
    assert empty.hint.code == "NO_MATCH"


def test_understood_normalizes_and_includes_mandate_attributes():
    catalog, _ = service(FakeCatalog(), required_attributes=("FREE_FROM_GLUTEN",))

    result = catalog.search(
        agent_key(), query("  JÄÄTELÖ  ", required_attributes=("FREE_FROM_LACTOSE",), category="1")
    )

    assert result.understood.query == "jaatelo"
    assert result.understood.required_attributes == ("FREE_FROM_GLUTEN", "FREE_FROM_LACTOSE")
    assert result.understood.category == "1"


def test_postgres_persists_one_search_with_the_response_facts(database):
    from sqlalchemy import select

    from app.adapters.clock import FixedClock
    from app.adapters.memory.repositories import InMemoryCartRepository, InMemoryOfferRepository
    from app.adapters.postgres.catalog import PostgresCatalog
    from app.adapters.postgres.repositories import (
        PostgresAuditRepository,
        PostgresMandateRepository,
    )
    from app.adapters.postgres.tables import audit_records
    from app.services.audit_service import AuditService
    from app.services.catalog_service import CatalogService
    from tests.adapters.samples import mandate
    from tests.fakes.offer_data import NOW

    products = PostgresCatalog(database)
    products.replace([item("1"), item("2", category="2")])
    mandates = PostgresMandateRepository(database)
    with database.transaction():
        mandates.add(replace(mandate(), required_attributes=()))
    audit = AuditService(
        PostgresAuditRepository(database),
        InMemoryCartRepository(),
        InMemoryOfferRepository(),
        FixedClock(NOW),
        database,
    )
    catalog = CatalogService(products, mandates, audit, database, 500)

    result = catalog.search(agent_key(), query())

    with database.reader() as connection:
        rows = connection.execute(select(audit_records)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["request_id"] == result.request_id
    assert rows[0]["buyer_id"] == agent_key().buyer_id
    assert rows[0]["body"]["step"] == "SEARCH"
    assert rows[0]["body"]["output_data"]["total_hits"] == result.total_hits == 2
    assert rows[0]["body"]["output_data"]["hint"]["code"] == "READY"
