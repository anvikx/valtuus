"""S2 category visibility, hint priority and audit completeness."""

from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from app.domain.catalog import Allergens, ContentPerSalesUnit
from app.domain.enums import AllergenStatus, Decision, Unit
from tests.adapters.samples import agent_key
from tests.fakes.catalog import item, query, service
from tests.fakes.offer_data import FakeCatalog

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
        "choices": [],
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
    assert {s.category: s.in_list for s in result.categories} == {
        "10": True,
        "1": False,
        "2": False,
        "3": False,
        "4": False,
        "5": False,
        "6": False,
        "7": False,
    }
    assert {p.product_id for p in result.candidates} == {"1", "2", "3", "4"}


def test_guard_preserves_total_and_category_counts_at_boundary():
    catalog, _ = service(FakeCatalog(*(item(str(i)) for i in range(501))))

    cut = catalog.search(agent_key(), query())

    assert len(cut.candidates) == 500
    assert cut.total_hits == cut.categories[0].hits == 501
    assert cut.hint.code == "GUARD_CUT"
    assert cut.categories[0].in_list is True
    catalog, _ = service(FakeCatalog(*(item(str(i)) for i in range(500))))
    complete = catalog.search(agent_key(), query())
    assert len(complete.candidates) == complete.total_hits == 500
    assert complete.hint.code == "READY"
    assert complete.categories[0].in_list is True


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
    assert result.categories[0].in_list is True
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


@pytest.mark.parametrize(
    "excluded_category,requested_category,content,requested_unit,expected",
    [
        pytest.param(
            "2",
            "1",
            ContentPerSalesUnit(Decimal(1), Unit.L),
            Unit.L,
            "NO_MATCH",
            id="other-category",
        ),
        pytest.param(
            "1",
            "1",
            ContentPerSalesUnit(Decimal(1), Unit.KG),
            Unit.L,
            "NO_MATCH",
            id="kg-for-litres",
        ),
        pytest.param(
            "1",
            "1",
            ContentPerSalesUnit(Decimal(1), Unit.L),
            Unit.KG,
            "NO_MATCH",
            id="litres-for-kg",
        ),
        pytest.param(
            "1",
            None,
            ContentPerSalesUnit(Decimal(1), Unit.KG),
            Unit.L,
            "NO_MATCH",
            id="opposite-unit-no-category",
        ),
        pytest.param(
            "1",
            "1",
            ContentPerSalesUnit(Decimal(1), Unit.L),
            Unit.L,
            "EXCLUDED_ONLY",
            id="eligible",
        ),
        pytest.param("1", "1", None, Unit.L, "EXCLUDED_ONLY", id="missing-content-stays"),
        pytest.param(
            "1",
            "1",
            ContentPerSalesUnit(Decimal(1), Unit.KG),
            Unit.PCS,
            "EXCLUDED_ONLY",
            id="pcs-does-not-restrict-content",
        ),
    ],
)
def test_hint_uses_only_exclusions_that_otherwise_fit(
    excluded_category,
    requested_category,
    content,
    requested_unit,
    expected,
):
    excluded = item(
        "excluded",
        category=excluded_category,
        content_per_sales_unit=content,
        allergens=Allergens(AllergenStatus.UNKNOWN, ()),
    )
    catalog, records = service(FakeCatalog(excluded), allergen_unknown_policy=Decision.DENY)

    result = catalog.search(agent_key(), query(category=requested_category, unit=requested_unit))

    assert result.hint.code == expected
    assert result.candidates == ()
    assert result.total_hits == 0
    assert result.categories == ()
    assert result.hint_category == requested_category
    assert [p.product_id for p in result.excluded] == ["excluded"]
    assert records.records[0].output_data["hint"]["code"] == expected


def test_unrelated_exclusion_does_not_override_no_match_with_missing_fields():
    excluded = item("excluded", category="2", allergens=Allergens(AllergenStatus.UNKNOWN, ()))
    catalog, _ = service(FakeCatalog(excluded), allergen_unknown_policy=Decision.DENY)

    result = catalog.search(agent_key(), query(category="1", quantity=None))

    assert result.hint.code == "NO_MATCH"
    assert result.missing_fields == ("quantity",)
    assert [p.product_id for p in result.excluded] == ["excluded"]


@pytest.mark.parametrize("category", [None, "2", "missing"])
def test_in_list_tracks_the_returned_category(category):
    catalog, _ = service(FakeCatalog(item("1", category="1"), item("2", category="2")))

    result = catalog.search(agent_key(), query(category=category))

    flags = {summary.category: summary.in_list for summary in result.categories}
    if category is None:
        assert result.hint_category == "1"
        assert flags == {"1": True, "2": False}
        assert [candidate.product_id for candidate in result.candidates] == ["1"]
    elif category == "2":
        assert result.hint_category == "2"
        assert flags == {"2": True}
        assert [candidate.product_id for candidate in result.candidates] == ["2"]
    else:
        assert result.hint_category == "missing"
        assert result.hint.code == "NO_MATCH"
        assert flags == {}
        assert result.candidates == ()


def _milks():
    return FakeCatalog(
        item("plain", attributes=("VEGETARIAN",)),
        item("lactose-free", attributes=("FREE_FROM_LACTOSE", "VEGETARIAN")),
        item("lactose-free-low-fat", attributes=("FREE_FROM_LACTOSE", "LOW_FAT")),
        item("other-type", category="2", attributes=("EU_ORGANIC_FARMING",)),
    )


def test_buyer_chooses_safety_and_type_attributes_before_offers():
    """'milk' covers lactose free and low fat milk, so the buyer must say which they need."""
    catalog, records = service(_milks())

    result = catalog.search(agent_key(), query())

    assert result.hint.code == "ASK_CHOICES"
    assert result.hint.sentence == (
        "Ask the buyer which choices they need, in one question. Search again with the chosen "
        "codes in required_attributes and the other codes in declined_attributes."
    )
    assert [(c.attribute, c.hits) for c in result.choices] == [
        ("FREE_FROM_LACTOSE", 2),
        ("LOW_FAT", 1),
    ]
    assert [c.product_id for c in result.candidates] == [
        "lactose-free",
        "lactose-free-low-fat",
        "plain",
    ]
    assert records.records[0].output_data["choices"] == [
        {"attribute": "FREE_FROM_LACTOSE", "hits": 2},
        {"attribute": "LOW_FAT", "hits": 1},
    ]


def test_answered_choices_are_not_asked_again():
    """Without this the agent asks forever: a declined code means the buyer does not care."""
    catalog, _ = service(_milks())

    result = catalog.search(
        agent_key(),
        query(required_attributes=("FREE_FROM_LACTOSE",), declined_attributes=("LOW_FAT",)),
    )

    assert result.hint.code == "READY"
    assert result.choices == ()


def test_required_code_wins_over_a_declined_one():
    """A safety need must never be dropped because the same code was also declined."""
    catalog, _ = service(_milks())

    result = catalog.search(
        agent_key(),
        query(
            required_attributes=("LOW_FAT",), declined_attributes=("LOW_FAT", "FREE_FROM_LACTOSE")
        ),
    )

    assert [c.product_id for c in result.candidates] == ["lactose-free-low-fat"]
    assert result.choices == ()


def test_mandate_attribute_is_never_a_choice():
    """The main user already decided it for every search."""
    catalog, _ = service(_milks(), required_attributes=("FREE_FROM_LACTOSE",))

    result = catalog.search(agent_key(), query())

    assert [c.attribute for c in result.choices] == ["LOW_FAT"]


def test_missing_fields_and_choices_go_in_one_question():
    catalog, _ = service(_milks())

    result = catalog.search(agent_key(), query(quantity=None))

    assert result.hint.code == "MISSING_FIELDS"
    assert result.hint.sentence == (
        "Ask the buyer for the missing values and the choices, in one question, before the offers."
    )
    assert [c.attribute for c in result.choices] == ["FREE_FROM_LACTOSE", "LOW_FAT"]


def test_choices_come_before_a_guard_cut():
    """A choice narrows the list, so the agent asks before it adds words."""
    catalog, _ = service(_milks(), candidate_guard=1)

    assert catalog.search(agent_key(), query()).hint.code == "ASK_CHOICES"
