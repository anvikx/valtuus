"""Search invariants are shared by the in-memory and PostgreSQL catalog adapters."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.adapters.postgres.catalog import PostgresCatalog
from app.api.results import search_response
from app.domain.catalog import Allergens, ContentPerSalesUnit
from app.domain.catalog_search import (
    VALID_ATTRIBUTES,
    NameMatcher,
    validate_query,
)
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


def test_unknown_declined_attribute_is_refused():
    with pytest.raises(InvalidRequestError):
        validate_query(query(declined_attributes=("ORGANIC",)))


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


def test_a_category_of_a_longer_phrase_is_not_the_default():
    """Every ice cream name says "cream", but a buyer who asks for cream wants cream."""
    products = [
        item("1", "Vanilla ice cream 5 l", category="41800"),
        item("2", "Chocolate ice cream 5 l", category="41800"),
        item("3", "Strawberry ice cream 5 l", category="41800"),
        item("4", "Whipping cream 1 l", category="10401"),
        item("5", "Cooking cream 1 l", category="10401"),
    ]
    catalog, _ = service(FakeCatalog(*products))

    result = catalog.search(agent_key(), query("cream"))

    assert result.hint_category == "10401"
    assert [c.category for c in result.categories] == ["10401", "41800"]


def test_whole_word_hits_pick_the_default_category():
    """A name that only holds the query inside a longer word is a weak hit."""
    products = [
        item("1", "Milkshake strawberry", category="22700"),
        item("2", "Milkshake vanilla", category="22700"),
        item("3", "Milkshake chocolate", category="22700"),
        item("4", "Milk 1 l", category="10400"),
        item("5", "Milk 10 l", category="10400"),
    ]
    catalog, _ = service(FakeCatalog(*products))

    assert catalog.search(agent_key(), query()).hint_category == "10400"


def test_close_categories_ask_the_buyer():
    """The search does not guess between butter and butter buns. The buyer picks."""
    products = [
        item("1", "Butter bun", category="41764"),
        item("2", "Butter croissant", category="41764"),
        item("3", "Butter cake", category="41764"),
        item("4", "Butter 500 g", category="10500"),
        item("5", "Butter 200 g", category="10500"),
    ]
    catalog, records = service(FakeCatalog(*products))

    result = catalog.search(agent_key(), query("butter"))

    assert result.hint.code == "ASK_CATEGORY"
    assert result.hint_category is None
    assert result.candidates == ()
    assert [(c.category, c.in_list) for c in result.categories] == [
        ("41764", False),
        ("10500", False),
    ]
    assert records.records[-1].output_data["offer_set_size"] == 0


def test_a_category_close_on_one_count_only_is_the_default():
    """kerma is a whole word in one name per category, but cream has many more hits."""
    products = [
        item("1", "Kerma 1 l", category="10401"),
        item("2", "Vispikerma 1 l", category="10401"),
        item("3", "Kuohukerma 1 l", category="10401"),
        item("4", "Laskiaispulla kerma", category="11030"),
    ]
    catalog, _ = service(FakeCatalog(*products))

    assert catalog.search(agent_key(), query("kerma")).hint_category == "10401"


def test_numeric_category_tie_break_and_no_match():
    catalog, records = service(FakeCatalog(item("1", category="10"), item("2", category="2")))

    assert [c.category for c in catalog.search(agent_key(), query()).categories] == ["2", "10"]
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


def test_unknown_allergens_stay_when_nothing_is_forbidden():
    """Missing allergen data matters only for an allergen the buyer forbids."""
    unknown = item("unknown", allergens=Allergens(AllergenStatus.UNKNOWN, ()))
    catalog, _ = service(
        FakeCatalog(unknown),
        forbidden_allergens=(),
        allergen_unknown_policy=Decision.DENY,
    )

    result = catalog.search(agent_key(), query())

    assert [p.product_id for p in result.candidates] == ["unknown"]
    assert result.excluded == ()


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

    assert len(result.candidates) == 40
    assert result.hint.code == "GUARD_CUT"
    catalog, _ = service(FakeCatalog(*(item(str(n)) for n in range(121))))
    result = catalog.search(agent_key(), query())
    assert len(result.candidates) == 40
    assert result.total_hits == 121
    # The preview is cut, but offers still see all 121, so nothing is hidden from them.
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
