from dataclasses import replace
from decimal import Decimal

import pytest

from app.domain.catalog import Allergens, ContentPerSalesUnit
from app.domain.enums import AllergenStatus, AllergenType, ReasonCode, SubstituteBasis, Unit
from app.domain.offer import Candidate
from app.domain.screening import reject
from app.domain.substitutes import is_equivalent, substitute_for
from tests.fakes.offer_data import MILK_ID, price, product, query, stock

_BOX_ID = "465039"
_FIVE_LITRES = ContentPerSalesUnit(Decimal(5), Unit.L)


def _box(unit_price: str = "5.25") -> Candidate:
    return Candidate(
        product=product(_BOX_ID, sales_unit="KI", content=_FIVE_LITRES),
        price=price(_BOX_ID, unit_price),
        availability=stock(_BOX_ID, sales_unit="KI"),
    )


def _not_delivered():
    return reject(MILK_ID, product().name, ReasonCode.NOT_AVAILABLE)


def test_the_same_known_allergens_make_an_equivalent() -> None:
    """464306 and 465039 both contain milk and nothing else: the demo pair is offered."""
    assert is_equivalent(product(), product(_BOX_ID))


@pytest.mark.parametrize(
    "allergens",
    [
        Allergens(AllergenStatus.KNOWN, (), {AllergenType.CONTAINS: ("AM", "AY")}),
        Allergens(
            AllergenStatus.KNOWN,
            (),
            {AllergenType.CONTAINS: ("AM",), AllergenType.MAY_CONTAIN: ("AP",)},
        ),
        Allergens(AllergenStatus.KNOWN, ("AW",), {AllergenType.CONTAINS: ("AM",)}),
    ],
)
def test_other_allergens_are_no_equivalent(allergens: Allergens) -> None:
    """A swap must not add an allergen, a trace or drop a free from claim the buyer relied on."""
    other = replace(product(_BOX_ID), allergens=allergens)

    assert not is_equivalent(product(), other)


def test_a_missing_may_contain_list_equals_an_empty_one() -> None:
    """Rows stored by an old image hold only CONTAINS. That must not hide a real equivalent."""
    old_row = replace(
        product(_BOX_ID),
        allergens=Allergens(AllergenStatus.KNOWN, (), {AllergenType.CONTAINS: ("AM",)}),
    )
    new_row = replace(
        product(),
        allergens=Allergens(
            AllergenStatus.KNOWN,
            (),
            {AllergenType.CONTAINS: ("AM",), AllergenType.MAY_CONTAIN: ()},
        ),
    )

    assert is_equivalent(new_row, old_row)


def test_unknown_allergens_are_no_equivalent() -> None:
    """Equal but unknown proves nothing: both could hold any allergen."""
    unknown = Allergens(AllergenStatus.UNKNOWN, ())

    assert not is_equivalent(
        replace(product(), allergens=unknown),
        replace(product(_BOX_ID), allergens=unknown),
    )


def test_the_price_difference_is_per_litre_not_per_sales_unit() -> None:
    """A 5 l box against a 1 l bottle: per sales unit it would read 4.24 EUR more."""
    marked = substitute_for(product(), price(), _not_delivered(), _box(), query())

    assert marked.price_difference_per_unit == Decimal("0.04")
    assert marked.product_id == MILK_ID
    assert marked.name == product().name
    assert marked.basis is SubstituteBasis.VALIO_PAIR
    assert marked.reason_code is ReasonCode.NOT_AVAILABLE
    assert marked.reason_sentence == "Valio Aimo cannot deliver this product."


def test_a_cheaper_substitute_has_a_negative_difference() -> None:
    marked = substitute_for(product(), price(), _not_delivered(), _box("4.95"), query())

    assert marked.price_difference_per_unit == Decimal("-0.02")


@pytest.mark.parametrize(
    ("requested_price", "content"),
    [(None, ContentPerSalesUnit(Decimal(1), Unit.L)), ("1.01", None)],
)
def test_no_difference_without_a_requested_price_per_litre(requested_price, content) -> None:
    """No price or no size: the person still sees the substitute, with no made up difference."""
    requested = product(content=content)
    known = None if requested_price is None else price(unit_price=requested_price)

    marked = substitute_for(requested, known, _not_delivered(), _box(), query())

    assert marked.price_difference_per_unit is None
