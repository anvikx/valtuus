from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.catalog import Allergens, ContentPerSalesUnit, Product
from app.domain.enums import AllergenStatus, AllergenType, ReasonCode, SubstituteBasis, Unit
from app.domain.offer import AvailabilitySnapshot, Candidate, Price, SubstituteFor
from app.domain.ranking import rank_offer_lines
from app.domain.screening import screen
from app.domain.substitutes import is_safe_pair, select_substitutes, substitute_pairs
from tests.fakes.offer_data import (
    MONDAY,
    NOW,
    SOURCE_TIME,
    price,
    product,
    query,
    stock,
)

_BUTTER_500 = "463437"
_BUTTER_200 = "462421"
_MILK_UHT = "464073"
_MILK_ARLA = "464768"
_TWELVE_LITRES = ContentPerSalesUnit(Decimal(12), Unit.L)
_TUESDAY = MONDAY + timedelta(days=1)
_LACTOSE_FREE_MILK_NAME = "Valio whole milk 1 l lactose free UHT"
_ARLA_NAME = "12 x Arla Whole milk drink 1 L UHT lactose free"


def _known(*codes: str) -> Allergens:
    return Allergens(
        status=AllergenStatus.KNOWN,
        free_from=(),
        declarations={AllergenType.CONTAINS: codes},
    )


def _milk(**fields) -> Product:
    return replace(
        product(_MILK_UHT),
        name=_LACTOSE_FREE_MILK_NAME,
        substitute_ids=(_MILK_ARLA,),
        **fields,
    )


def _arla(**fields) -> Product:
    return replace(product(_MILK_ARLA), name=_ARLA_NAME, **fields)


def _snapshot(*items) -> AvailabilitySnapshot:
    return AvailabilitySnapshot(SOURCE_TIME, {item.product_id: item for item in items})


def _select(original: Product, substitute: Product, prices, stocks, **query_fields):
    request = query(original.product_id, **query_fields)
    screened = {
        original.product_id: screen(
            original,
            prices.get(original.product_id),
            next((s for s in stocks if s.product_id == original.product_id), None),
            request,
            NOW,
        ),
    }
    pairs = substitute_pairs([original], {substitute.product_id: substitute}.get)
    chosen = select_substitutes(
        pairs,
        screened,
        prices,
        _snapshot(*stocks),
        request,
        NOW,
    )
    return chosen, screened


def _rejected_original_world(original_price: Price | None = None, sub_price: Price | None = None):
    prices = {
        _MILK_ARLA: sub_price or price(_MILK_ARLA, "1.20"),
    }
    if original_price is not None:
        prices[_MILK_UHT] = original_price
    # No stock line for the original: NOT_AVAILABLE.
    return prices, [stock(_MILK_ARLA)]


@pytest.mark.parametrize(
    ("original", "substitute", "is_safe"),
    [
        pytest.param(_known("AM"), _known("AM"), True, id="equal"),
        pytest.param(_known("AM"), _known("AM", "GL"), False, id="different"),
        pytest.param(
            _known("AM"),
            replace(_known("AM"), status=AllergenStatus.UNKNOWN),
            False,
            id="unknown substitute",
        ),
        pytest.param(
            replace(_known("AM"), status=AllergenStatus.UNKNOWN),
            _known("AM"),
            False,
            id="unknown original",
        ),
        pytest.param(
            _known("AM"),
            Allergens(
                AllergenStatus.KNOWN,
                (),
                {AllergenType.MAY_CONTAIN: ("AM",)},
            ),
            False,
            id="may contain is not contains",
        ),
    ],
)
def test_a_pair_is_safe_only_with_equal_known_allergens(original, substitute, is_safe) -> None:
    """A guest allergic to milk must not get a product with another allergen declaration.

    A MAY_CONTAIN that became CONTAINS has the same flat list in a union, so the
    declarations are compared, not only the merged list.
    """
    result = is_safe_pair(
        replace(product(_BUTTER_500), allergens=original),
        replace(product(_BUTTER_200), allergens=substitute),
    )

    assert result is is_safe


def test_a_requested_product_is_not_offered_as_a_substitute() -> None:
    """The agent asked for it already. A second line would count the same product twice."""
    butter = replace(product(_BUTTER_500), substitute_ids=(_BUTTER_200,))
    other = product(_BUTTER_200)

    pairs = substitute_pairs([butter, other], {_BUTTER_200: other}.get)

    assert pairs == ()


def test_a_rejected_original_gets_its_pair_with_the_reason_it_got() -> None:
    """The main user must see why the substitute is there, in the same words as the reject."""
    original, substitute = _milk(), _arla()
    prices, stocks = _rejected_original_world(price(_MILK_UHT, "1.00"))

    (chosen,), screened = _select(original, substitute, prices, stocks)

    origin = chosen.substitute_for
    assert origin.product_id == _MILK_UHT
    assert origin.name == _LACTOSE_FREE_MILK_NAME
    assert origin.basis is SubstituteBasis.VALIO_PAIR
    assert origin.reason_code is ReasonCode.NOT_AVAILABLE
    assert origin.reason_sentence == screened[_MILK_UHT].reason_sentence
    assert origin.price_difference_per_unit == Decimal("0.20")
    assert origin.per is Unit.L


def test_a_late_original_gets_its_pair() -> None:
    """A product that arrives after the deadline is as useless to the buyer as a rejected one."""
    original, substitute = _milk(), _arla()
    prices = {_MILK_UHT: price(_MILK_UHT, "1.00"), _MILK_ARLA: price(_MILK_ARLA, "0.90")}
    stocks = [stock(_MILK_UHT, available_date=_TUESDAY), stock(_MILK_ARLA)]

    (chosen,), _ = _select(original, substitute, prices, stocks)

    assert chosen.substitute_for.reason_code is ReasonCode.DELIVERY_AFTER_DEADLINE
    assert "after" in chosen.substitute_for.reason_sentence
    assert chosen.substitute_for.price_difference_per_unit == Decimal("-0.10")


def test_an_original_that_can_be_delivered_gets_no_substitute() -> None:
    """The agent asked for this product and it works. An unasked line only adds noise."""
    original, substitute = _milk(), _arla()
    prices = {_MILK_UHT: price(_MILK_UHT), _MILK_ARLA: price(_MILK_ARLA)}
    stocks = [stock(_MILK_UHT), stock(_MILK_ARLA)]

    chosen, _ = _select(original, substitute, prices, stocks)

    assert chosen == ()


@pytest.mark.parametrize(
    "arla_stock",
    [
        pytest.param(stock(_MILK_ARLA, amount=0), id="rejected"),
        pytest.param(stock(_MILK_ARLA, available_date=_TUESDAY), id="late"),
    ],
)
def test_a_rejected_or_late_substitute_is_dropped(arla_stock) -> None:
    """A substitute that cannot meet the request helps nobody and was not asked for."""
    original, substitute = _milk(), _arla()
    prices = {_MILK_ARLA: price(_MILK_ARLA)}

    chosen, _ = _select(original, substitute, prices, [arla_stock])

    assert chosen == ()


def test_a_partial_stock_substitute_stays_with_its_reason() -> None:
    """The main user can still accept part of it, so the reason code must show."""
    original, substitute = _milk(), _arla()
    prices = {_MILK_ARLA: price(_MILK_ARLA)}

    (chosen,), _ = _select(original, substitute, prices, [stock(_MILK_ARLA, amount=200)])
    (line,) = rank_offer_lines([chosen], query(_MILK_UHT))

    assert line.reason_codes == (ReasonCode.PARTIAL_AVAILABILITY,)
    assert line.substitute_for is chosen.substitute_for


def test_the_price_difference_is_unknown_when_the_original_has_no_price() -> None:
    """A made up difference would mislead the approver. null says the gap is unknown."""
    original, substitute = _milk(), _arla()
    prices, stocks = _rejected_original_world(None)
    stocks.append(stock(_MILK_UHT))

    (chosen,), _ = _select(original, substitute, prices, stocks)

    assert chosen.substitute_for.reason_code is ReasonCode.NO_PRICE
    assert chosen.substitute_for.price_difference_per_unit is None


def test_the_price_difference_is_unknown_when_the_original_has_no_size() -> None:
    """Without a size the price per litre of the original cannot be computed."""
    original, substitute = _milk(content_per_sales_unit=None), _arla()
    prices = {_MILK_UHT: price(_MILK_UHT), _MILK_ARLA: price(_MILK_ARLA)}
    stocks = [stock(_MILK_UHT), stock(_MILK_ARLA)]

    (chosen,), _ = _select(original, substitute, prices, stocks)

    assert chosen.substitute_for.reason_code is ReasonCode.NO_CONTENT_DATA
    assert chosen.substitute_for.price_difference_per_unit is None


def test_the_price_difference_compares_per_litre_not_per_pack() -> None:
    """A 12 L pack at 12.60 EUR is 1.05 per L. Against 1.00 per L the gap is 0.05, not 11.60."""
    original = _milk()
    substitute = _arla(content_per_sales_unit=_TWELVE_LITRES)
    prices, stocks = _rejected_original_world(
        price(_MILK_UHT, "1.00"),
        price(_MILK_ARLA, "12.60"),
    )

    (chosen,), _ = _select(original, substitute, prices, stocks)

    assert chosen.substitute_for.price_difference_per_unit == Decimal("0.05")


def test_the_price_difference_uses_the_unit_of_the_request() -> None:
    """Butter 500 g at 2.00 EUR and 200 g at 1.00 EUR, asked in KG: 4.00 and 5.00 per KG."""
    original = replace(
        product(_BUTTER_500, content=ContentPerSalesUnit(Decimal("0.5"), Unit.KG)),
        name="Valio Eila® butter 500 g salted lactose free",
        substitute_ids=(_BUTTER_200,),
    )
    substitute = replace(
        product(_BUTTER_200, content=ContentPerSalesUnit(Decimal("0.2"), Unit.KG)),
        name="Valio Eila® butter 200 g lactose free",
    )
    prices = {_BUTTER_500: price(_BUTTER_500, "2.00"), _BUTTER_200: price(_BUTTER_200, "1.00")}
    stocks = [stock(_BUTTER_200)]

    (chosen,), _ = _select(original, substitute, prices, stocks, quantity="10", unit=Unit.KG)

    assert chosen.substitute_for.price_difference_per_unit == Decimal("1.00")
    assert chosen.substitute_for.per is Unit.KG


def test_substitute_lines_rank_after_every_requested_line() -> None:
    """The agent orders rank 1 first. A substitute must never lead, even when it is cheaper."""
    request = query(_MILK_UHT, "other")
    dear = Candidate(product("other"), price("other", "5.00"), stock("other"))
    cheap_substitute = replace(
        Candidate(_arla(), price(_MILK_ARLA, "0.10"), stock(_MILK_ARLA)),
        substitute_for=_origin(),
    )

    lines = rank_offer_lines([cheap_substitute, dear], request)

    assert [(line.rank, line.product_id) for line in lines] == [(1, "other"), (2, _MILK_ARLA)]
    assert lines[0].substitute_for is None


def test_one_line_per_substitute_even_when_two_originals_name_it() -> None:
    """Two lines of one product would double the cart quantity. The first original owns it."""
    first = replace(product("A1"), substitute_ids=(_MILK_ARLA,))
    second = replace(product("A2"), substitute_ids=(_MILK_ARLA,))
    substitute = _arla()
    request = query("A1", "A2")
    screened = {
        "A1": screen(first, None, None, request, NOW),
        "A2": screen(second, None, None, request, NOW),
    }
    pairs = substitute_pairs([first, second], {_MILK_ARLA: substitute}.get)

    chosen = select_substitutes(
        pairs,
        screened,
        {_MILK_ARLA: price(_MILK_ARLA)},
        _snapshot(stock(_MILK_ARLA)),
        request,
        NOW,
    )

    assert [item.substitute_for.product_id for item in chosen] == ["A1"]


def _origin():
    return SubstituteFor(
        product_id=_MILK_UHT,
        name=_LACTOSE_FREE_MILK_NAME,
        basis=SubstituteBasis.VALIO_PAIR,
        reason_code=ReasonCode.NOT_AVAILABLE,
        reason_sentence="Valio Aimo cannot deliver this product.",
        price_difference_per_unit=None,
        per=Unit.L,
    )
