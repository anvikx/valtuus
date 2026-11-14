"""Search invariants are shared by the in-memory and PostgreSQL catalog adapters."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import (
    InMemoryCartRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryUnitOfWork,
)
from app.adapters.postgres.catalog import PostgresCatalog
from app.adapters.product_store import ProductStore
from app.api.results import search_response
from app.domain.catalog import Allergens, ContentPerSalesUnit, SearchQuery
from app.domain.catalog_search import VALID_ATTRIBUTES, NameMatcher, validate_query
from app.domain.enums import AllergenStatus, AllergenType, Decision, Unit
from app.domain.errors import InvalidRequestError
from app.services.audit_service import AuditService
from app.services.catalog_service import CatalogService
from tests.adapters.samples import agent_key, mandate
from tests.fakes.offer_data import MONDAY, NOW, FakeCatalog, product


class Records:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


def query(words="milk", **values):
    return replace(SearchQuery(words, (), Decimal("10"), Unit.L, MONDAY, ()), **values)


def item(pid="1", name="Milk", **values):
    return replace(product(pid, lot_size=Decimal(1)), names={"en": name}, name=name, **values)


def service(catalog, **rules):
    mandates = InMemoryMandateRepository()
    mandates.add(replace(mandate(), required_attributes=(), **rules))
    records = Records()
    uow = InMemoryUnitOfWork()
    audit = AuditService(
        records,
        InMemoryCartRepository(),
        InMemoryOfferRepository(),
        FixedClock(NOW),
        uow,
    )
    return CatalogService(catalog, mandates, audit, uow, 500), records


@pytest.mark.parametrize(
    "name", ["Milk free", "Milk-free", "Milkfree", "mjölkfri", "maitoton", "maitovapaa"]
)
def test_negated_names_do_not_match(name):
    word = "milk" if name.startswith("Milk") else "mjolk" if name.startswith("mj") else "maito"

    assert NameMatcher(word).match(item(name=name)) is None


def test_each_name_must_contain_all_words_and_another_name_can_match():
    matcher = NameMatcher("milk drink")
    split = replace(
        item(),
        names={"en": "Milk", "fi": "Drink"},
    )
    valid = replace(item(), names={"en": "Milk free", "sv": "Milkdrink"})

    assert matcher.match(split) is None
    assert NameMatcher("milk").match(valid).kind == "INSIDE_WORD"
    assert NameMatcher("milk").match(item(name="Milk chocolate free")) is not None


@pytest.mark.parametrize("words", ["", "ab", "milk ab", "one two three four five six"])
def test_invalid_query(words):
    with pytest.raises(InvalidRequestError):
        validate_query(query(words))


def test_unknown_attribute_names_all_valid_codes():
    with pytest.raises(InvalidRequestError) as caught:
        validate_query(query(required_attributes=("ORGANIC",)))

    assert all(code in caught.value.message for code in VALID_ATTRIBUTES)
    assert validate_query(query("JÄÄTELÖ")) == "jaatelo"


@pytest.mark.parametrize(
    "language,name,word",
    [("en", "Café", "cafe"), ("fi", "Jäätelö", "jaatelo"), ("sv", "Mjölk", "mjolk")],
)
def test_accent_folding_in_all_languages(language, name, word):
    catalog, _ = service(FakeCatalog(replace(item(), names={language: name})))

    assert len(catalog.search(agent_key(), query(word)).candidates) == 1


def test_category_selection_and_stable_match_order():
    products = [
        item("5", "Milkshake"),
        item("4", "Fresh milk"),
        item("3", "Milk"),
        item("2", "Milk"),
        item("1", "Milk", category="2"),
    ]
    catalog, records = service(FakeCatalog(*products))

    result = catalog.search(agent_key(), query())

    assert result.hint_category == "10400"
    assert [p.product_id for p in result.candidates] == ["2", "3", "4", "5"]
    assert [p.match for p in result.candidates] == ["WHOLE_WORD"] * 3 + ["INSIDE_WORD"]
    assert search_response(result).hint_category == "10400"
    assert len(records.records) == 1
    assert records.records[0].output_data["candidate_ids"] == ["2", "3", "4", "5"]
    assert catalog.search(agent_key(), query(category="2")).candidates[0].product_id == "1"
    repeated = catalog.search(agent_key(), query())
    assert repeated.candidates == result.candidates
    assert repeated.request_id != result.request_id
    assert records.records[0].request_id == result.request_id
    assert records.records[0].buyer_id == agent_key().buyer_id


def test_numeric_category_tie_break_and_no_match():
    catalog, records = service(FakeCatalog(item("1", category="10"), item("2", category="2")))

    assert catalog.search(agent_key(), query()).hint_category == "2"
    assert catalog.search(agent_key(), query("xyzzy")).candidates == ()
    assert records.records[-1].sentence == "NO_MATCH"


@pytest.mark.parametrize(
    "unit,expected",
    [
        (Unit.L, {"L", "missing", "unknown"}),
        (Unit.KG, {"KG", "missing", "unknown"}),
        (Unit.PCS, {"L", "KG", "missing", "unknown"}),
    ],
)
def test_unit_fit_keeps_unknown_content(unit, expected):
    products = [
        item("L"),
        item("KG", content_per_sales_unit=ContentPerSalesUnit(Decimal(1), Unit.KG)),
        item("missing", content_per_sales_unit=None),
        item("unknown", content_per_sales_unit=ContentPerSalesUnit(Decimal(1), None)),
    ]
    catalog, _ = service(FakeCatalog(*products))

    result = catalog.search(agent_key(), query(unit=unit))

    assert {p.product_id for p in result.candidates} == expected
    assert search_response(result).candidates


def test_attributes_and_allergens_before_category_and_unit():
    products = [
        item("ok", attributes=("FREE_FROM_LACTOSE",)),
        item("no-claim"),
        item(
            "forbidden",
            attributes=("FREE_FROM_LACTOSE",),
            allergens=Allergens(AllergenStatus.KNOWN, (), {AllergenType.MAY_CONTAIN: ("nuts",)}),
        ),
        item(
            "unknown",
            attributes=("FREE_FROM_LACTOSE",),
            allergens=Allergens(AllergenStatus.UNKNOWN, ()),
        ),
    ]
    catalog, _ = service(FakeCatalog(*products), allergen_unknown_policy=Decision.DENY)

    result = catalog.search(agent_key(), query(required_attributes=("FREE_FROM_LACTOSE",)))

    assert [p.product_id for p in result.candidates] == ["ok"]
    assert {p.product_id for p in result.excluded} == {"forbidden", "unknown"}


def test_complete_category_and_safety_guard():
    catalog, _ = service(FakeCatalog(*(item(str(n)) for n in range(501))))

    result = catalog.search(agent_key(), query())

    assert len(result.candidates) == 500
    assert result.truncated
    catalog, _ = service(FakeCatalog(*(item(str(n)) for n in range(121))))
    result = catalog.search(agent_key(), query())
    assert len(result.candidates) == 121
    assert not result.truncated


def test_postgres_uses_exact_name_rules_after_prefilter(database):
    store = PostgresCatalog(database)
    store.replace(
        [
            item("1", "Milk free"),
            item("2", "Milkdrink"),
            replace(item("3"), names={"en": "Milk", "fi": "Drink"}),
            item(
                "4", "Milk drink", content_per_sales_unit=ContentPerSalesUnit(Decimal(1), Unit.KG)
            ),
        ]
    )
    catalog, _ = service(store)

    result = catalog.search(agent_key(), query("milk drink"))

    assert [p.product_id for p in result.candidates] == ["2"]


def test_real_file_search_counts(database):
    from pathlib import Path

    data_dir = Path(__file__).resolve().parents[2] / "data"
    if not (data_dir / "valio_products.json").exists():
        pytest.skip("Private challenge catalog is not present")
    store = ProductStore(data_dir)
    _LOAD_CATALOG(store, store.local_files())
    persisted = PostgresCatalog(database)
    persisted.replace(store.products())
    catalog, _ = service(persisted)
    for product_id, amount, unit, source in (
        ("460020", Decimal(50), Unit.PCS, "DATA"),
        ("460367", Decimal(4), Unit.PCS, "DATA"),
        ("460503", Decimal(40), Unit.PCS, "DATA"),
        ("460498", Decimal(1000), Unit.PCS, "NAME"),
        ("464306", Decimal(1), Unit.L, "DATA"),
    ):
        content = persisted.get(product_id).content_per_sales_unit
        assert (content.value, content.unit, content.source) == (amount, unit, source)
    cases = [
        ("milk", ("FREE_FROM_LACTOSE",), Unit.L, None, "10400", 33),
        ("milk drink", ("FREE_FROM_LACTOSE",), Unit.L, None, "10400", 21),
        ("maito", ("FREE_FROM_LACTOSE",), Unit.L, None, "10400", 31),
        ("milk", (), Unit.L, None, "10400", 86),
        # Four dual weight/volume names have unknown content in the existing parser.
        # Search must keep them; this file therefore has 96, versus the spec snapshot's 92.
        ("cream", (), Unit.L, None, "41820", 96),
        ("cream", (), Unit.L, "10401", "10401", 43),
        ("butter", (), Unit.KG, None, "41764", 27),
        ("butter", (), Unit.KG, "10500", "10500", 19),
        ("oat drink", (), Unit.L, None, "10402", 36),
        ("chicken", (), None, None, "41710", 121),
    ]
    for words, attributes, unit, category, expected_category, count in cases:
        result = catalog.search(
            agent_key(),
            query(
                words,
                required_attributes=attributes,
                unit=unit,
                category=category,
            ),
        )
        assert (result.hint_category, len(result.candidates)) == (expected_category, count), words
        assert not result.truncated
    plain = catalog.search(agent_key(), query("jaatelo", unit=None))
    accented = catalog.search(agent_key(), query("jäätelö", unit=None))
    assert plain.candidates == accented.candidates
    result = catalog.search(agent_key(), query("milk", required_attributes=("FREE_FROM_LACTOSE",)))
    assert "475604" not in {p.product_id for p in result.candidates}


# Keep the real loader before the autouse fixture disables startup file loading.
_LOAD_CATALOG = ProductStore.load


def test_fried_is_not_the_negation_fri():
    assert NameMatcher("chicken").match(item(name="Chicken Fried thighmeat")) is not None


def test_one_litre_sales_units_and_unknown_quantity():
    catalog, _ = service(FakeCatalog(item()))

    result = catalog.search(agent_key(), query(quantity=Decimal("2.5")))

    assert result.candidates[0].sales_units_needed == 3
    assert result.candidates[0].quantity_delivered == Decimal(3)
    missing = catalog.search(agent_key(), query(quantity=None))
    assert missing.candidates[0].sales_units_needed is None
    assert "quantity" in missing.missing


def test_best_language_name_determines_sort_order():
    catalog, _ = service(
        FakeCatalog(
            replace(item("1", "Milkshake"), names={"en": "Milkshake", "fi": "Milk"}),
            item("2", "Fresh milk"),
        )
    )

    result = catalog.search(agent_key(), query())

    assert [p.product_id for p in result.candidates] == ["1", "2"]
    assert result.candidates[0].match == "WHOLE_WORD"
