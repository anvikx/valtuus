"""Search invariants are shared by the in-memory and PostgreSQL catalog adapters."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.adapters.postgres.catalog import PostgresCatalog
from app.adapters.product_store import ProductStore
from app.api.results import search_response
from app.domain.catalog import Allergens, ContentPerSalesUnit
from app.domain.catalog_search import VALID_ATTRIBUTES, NameMatcher, validate_query
from app.domain.enums import AllergenStatus, AllergenType, Decision, Unit
from app.domain.errors import InvalidRequestError
from tests.adapters.samples import agent_key
from tests.fakes.catalog import item, query, service
from tests.fakes.offer_data import FakeCatalog


@pytest.mark.parametrize(
    "name", ["Milk free", "Milk-free", "Milkfree", "mjölkfri", "maitoton", "maitovapaa"]
)
def test_negated_names_do_not_match(name):
    word = "milk" if name.startswith("Milk") else "mjolk" if name.startswith("mj") else "maito"

    assert NameMatcher(word).match(item(name=name)) is None


@pytest.mark.parametrize(
    "words,name",
    [
        ("gluten free bread", "Gluten free bread"),
        ("lactose free milk", "Lactose-free milk 1 l"),
        ("mjolk fri", "Mjölkfri dryck"),
    ],
)
def test_a_free_from_query_matches_its_own_negation(words, name):
    """The buyer asks for the free-from product, so its name must not count as negated."""
    assert NameMatcher(words).match(item(name=name)) is not None


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
    assert records.records[-1].output_data["hint"]["code"] == "NO_MATCH"


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


@pytest.mark.parametrize("category", [None, "1"])
def test_exclusions_are_reported_before_the_category_filter(category):
    unknown = Allergens(AllergenStatus.UNKNOWN, ())
    products = [
        item("ok", category="1"),
        item("same", category="1", allergens=unknown),
        item("other", category="2", allergens=unknown),
    ]
    catalog, _ = service(FakeCatalog(*products), allergen_unknown_policy=Decision.DENY)

    result = catalog.search(agent_key(), query(category=category))

    assert {p.product_id for p in result.excluded} == {"same", "other"}


def test_no_match_names_every_excluded_product():
    """With no candidate there is no category, and the buyer still needs to know why."""
    unknown = Allergens(AllergenStatus.UNKNOWN, ())
    products = [
        item("a", category="1", allergens=unknown),
        item("b", category="2", allergens=unknown),
    ]
    catalog, _ = service(FakeCatalog(*products), allergen_unknown_policy=Decision.DENY)

    result = catalog.search(agent_key(), query())

    assert {p.product_id for p in result.excluded} == {"a", "b"}


def test_complete_category_and_safety_guard():
    catalog, _ = service(FakeCatalog(*(item(str(n)) for n in range(501))))

    result = catalog.search(agent_key(), query())

    assert len(result.candidates) == 500
    assert result.hint.code == "GUARD_CUT"
    catalog, _ = service(FakeCatalog(*(item(str(n)) for n in range(121))))
    result = catalog.search(agent_key(), query())
    assert len(result.candidates) == 121
    assert result.hint.code == "READY"


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
        assert [summary.category for summary in result.categories if summary.in_list] == [
            expected_category,
        ]
        if unit is None:
            assert result.hint.code == "MISSING_FIELDS"
            assert result.missing_fields == ("unit",)
        else:
            assert result.hint.code == "READY"
    cream = catalog.search(agent_key(), query("cream"))
    whipping = next(summary for summary in cream.categories if summary.category == "10401")
    assert whipping.hits == 43
    assert whipping.in_list is False
    assert len(whipping.examples) == 2
    assert any("whip" in name.casefold() for name in whipping.examples)
    assert cream.total_hits > len(cream.candidates)
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
    assert "quantity" in missing.missing_fields


def test_pieces_fill_packs_by_their_piece_count():
    """25 eggs in packs of 10 is 3 packs, not 25 packs of 250 eggs."""
    eggs = item(name="Eggs", content_per_sales_unit=ContentPerSalesUnit(Decimal(10), Unit.PCS))
    catalog, _ = service(FakeCatalog(eggs))

    result = catalog.search(agent_key(), query("eggs", quantity=Decimal(25), unit=Unit.PCS))

    (found,) = result.candidates
    assert found.sales_units_needed == 3
    assert found.quantity_delivered == Decimal(30)
    assert found.quantity_over_request == Decimal(5)


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
