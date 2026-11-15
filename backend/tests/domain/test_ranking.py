from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import OfferTier, ReasonCode, StockModel, Unit
from app.domain.offer import Candidate, ComparisonPrice
from app.domain.ranking import rank_offer_lines
from tests.fakes.offer_data import MILK_ID, MONDAY, price, product, query, stock

_UNKNOWN_STOCK_MARKER = 999_999


def _candidate(product_id: str = MILK_ID, unit_price: str = "1.01", **stock_fields) -> Candidate:
    return Candidate(
        product=product(product_id),
        price=price(product_id, unit_price),
        availability=stock(product_id, **stock_fields),
    )


def test_run_1_ranks_the_cheapest_stocked_milk_best() -> None:
    """Run 1 of the demo: 1000 L, 464306 at 1.01 EUR per litre, in stock."""
    (line,) = rank_offer_lines([_candidate()], query())

    assert (line.rank, line.tier, line.product_id) == (1, OfferTier.BEST, MILK_ID)
    assert line.comparison_price == ComparisonPrice(Decimal("1.01"), Unit.L)
    assert line.sales_units_needed == 1000
    assert line.line_total == Decimal("1010.00")
    assert line.available_qty is None
    assert line.reason_codes == ()
    assert line.max_auto_qty is None


def test_full_stock_beats_a_cheaper_partial_stock() -> None:
    """The agent orders rank 1 first. A cheap line that cannot deliver all must not lead."""
    partial = _candidate("cheap", "0.90", amount=200)
    full = _candidate("full", "1.01")

    lines = rank_offer_lines([partial, full], query())

    assert [line.product_id for line in lines] == ["full", "cheap"]
    assert lines[1].reason_codes == (ReasonCode.PARTIAL_AVAILABILITY,)
    assert lines[1].reason_sentences == ("Only 200 of 1000 in stock.",)
    assert lines[1].available_qty == 200


def test_a_late_line_is_last_with_every_reason() -> None:
    """Late and partial together: the date is the harder miss, so it is group C."""
    tuesday = MONDAY + timedelta(days=1)
    late = _candidate("late", "0.50", amount=200, available_date=tuesday)
    unconfirmed = _candidate("terminal", "1.20", model=StockModel.TERMINAL)

    lines = rank_offer_lines([late, unconfirmed], query())

    assert [line.product_id for line in lines] == ["terminal", "late"]
    assert lines[1].reason_codes == (
        ReasonCode.PARTIAL_AVAILABILITY,
        ReasonCode.DELIVERY_AFTER_DEADLINE,
    )
    assert lines[1].reason_sentences[1] == "The first delivery is Tue 17 Nov, after Mon 16 Nov."


def test_no_deliver_by_never_makes_a_line_late() -> None:
    """With no date, the gateway asks for the earliest delivery, so any date is on time."""
    later = _candidate(available_date=MONDAY + timedelta(days=3))

    (line,) = rank_offer_lines([later], query(deliver_by=None))

    assert line.reason_codes == ()


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(StockModel.TERMINAL, id="terminal"),
        pytest.param(None, id="no logistic model"),
    ],
)
@pytest.mark.parametrize("amount", [10, 999_999, 666_666_666, 9_999_999_999])
def test_unconfirmed_stock_is_group_b_with_no_count(model, amount) -> None:
    unconfirmed = _candidate("unconfirmed", "0.90", model=model, amount=amount)

    lines = rank_offer_lines([unconfirmed, _candidate()], query())

    assert [line.product_id for line in lines] == [MILK_ID, "unconfirmed"]
    assert lines[1].reason_codes == (ReasonCode.STOCK_UNCONFIRMED,)
    assert lines[1].available_qty is None


@pytest.mark.parametrize(
    ("amount", "reasons"),
    [
        (_UNKNOWN_STOCK_MARKER, (ReasonCode.STOCK_UNCONFIRMED,)),
        (1_000_000, ()),
        (666_666_666, ()),
        (9_999_999_999, ()),
    ],
)
def test_unknown_stock_amounts_are_not_compared_with_the_need(amount, reasons) -> None:
    """Unknown amounts must never be compared with the requested quantity (D35)."""
    (line,) = rank_offer_lines(
        [_candidate(amount=amount)],
        query(quantity=str(amount + 1)),
    )

    assert line.reason_codes == reasons
    assert line.available_qty is None


@pytest.mark.parametrize("amount", [1, 200, 999_998])
def test_stock_below_the_marker_is_compared_with_the_need(amount) -> None:
    """A real count below the marker must still reveal insufficient stock."""
    (line,) = rank_offer_lines([_candidate(amount=amount)], query(quantity=str(amount + 1)))

    assert line.available_qty == amount
    assert line.reason_codes == (ReasonCode.PARTIAL_AVAILABILITY,)
    assert line.reason_sentences == (f"Only {amount} of {amount + 1} in stock.",)


def test_only_the_first_three_ranks_get_a_tier() -> None:
    candidates = [_candidate(f"p{index}", f"1.0{index}") for index in range(4)]

    lines = rank_offer_lines(candidates, query())

    assert [line.tier for line in lines] == [
        OfferTier.BEST,
        OfferTier.BETTER,
        OfferTier.GOOD,
        None,
    ]


def test_equal_prices_rank_by_product_id() -> None:
    """The same data must give the same rank 1 on every call."""
    lines = rank_offer_lines([_candidate("b"), _candidate("a")], query())

    assert [line.product_id for line in lines] == ["a", "b"]


@pytest.mark.parametrize("amount", [384, 2000])
@pytest.mark.parametrize("brand", ["Arla", "ARLA"])
def test_preferred_brand_comes_first(amount, brand):
    """A cheaper alternative must not displace the buyer's preferred brand."""
    preferred = replace(
        _candidate("arla", "1.50", amount=amount),
        product=replace(product("arla"), brand=brand),
    )

    lines = rank_offer_lines(
        [_candidate("valio", "1.01"), preferred],
        replace(query(), preferred_brands=("Arla",)),
    )

    assert [line.product_id for line in lines] == ["arla", "valio"]


def test_on_time_beats_late_preference():
    preferred = replace(
        _candidate("arla", available_date=MONDAY + timedelta(days=1)),
        product=replace(product("arla"), brand="Arla"),
    )

    lines = rank_offer_lines(
        [preferred, _candidate("valio")],
        replace(query(), preferred_brands=("Arla",)),
    )

    assert [line.product_id for line in lines] == ["valio", "arla"]


def test_a_box_ranks_on_its_price_per_litre() -> None:
    """A 6 x 1 l box at 6.00 costs 1.00 per litre, so it beats a 1 l pack at 1.01."""
    box = replace(
        _candidate("box", "6.00"),
        product=product("box", content=ContentPerSalesUnit(Decimal(6), Unit.L)),
    )

    lines = rank_offer_lines([_candidate(), box], query(quantity="12"))

    assert [line.product_id for line in lines] == ["box", MILK_ID]
    assert lines[0].comparison_price == ComparisonPrice(Decimal("1.00"), Unit.L)
    assert lines[0].sales_units_needed == 2


@pytest.mark.parametrize(
    ("pack_size", "quantity", "boxes"),
    [
        pytest.param("5", "1000", 200, id="1000-l-five-litre-boxes"),
        pytest.param("5", "12", 3, id="12-l-five-litre-boxes"),
        pytest.param("20", "1000", 50, id="1000-l-two-times-10-l-boxes"),
        pytest.param("20", "41", 3, id="41-l-two-times-10-l-boxes"),
    ],
)
def test_offer_uses_full_box_count(pack_size, quantity, boxes):
    """Offer quantities and totals must count boxes rather than the litres inside them."""
    boxed = replace(
        _candidate("box", "7.00"),
        product=product("box", content=ContentPerSalesUnit(Decimal(pack_size), Unit.L)),
    )

    (line,) = rank_offer_lines([boxed], query("box", quantity=quantity))

    assert line.sales_units_needed == boxes
    assert line.line_total == Decimal("7.00") * boxes


def test_a_lot_size_under_1_orders_whole_sales_units() -> None:
    """16,872 products have allowedLotSize 0.01. It counts as 1 (D37), so 2.5 L is 3 packs."""
    candidate = replace(_candidate(), product=product(lot_size=Decimal("0.01")))

    (line,) = rank_offer_lines([candidate], query(quantity="2.5"))

    assert line.sales_units_needed == 3
    assert line.line_total == Decimal("3.03")


def test_a_product_that_was_not_screened_cannot_be_ranked() -> None:
    """A litre price from kilograms must fail loudly, not rank on a wrong number."""
    kilos = replace(
        _candidate(),
        product=product(content=ContentPerSalesUnit(Decimal(1), Unit.KG)),
    )

    with pytest.raises(ValueError, match="does not fit"):
        rank_offer_lines([kilos], query(unit=Unit.L))


def test_unconfirmed_stock_marker_does_not_outrank_confirmed_stock():
    unknown = _candidate("unknown", "0.50", amount=_UNKNOWN_STOCK_MARKER)
    confirmed = _candidate("confirmed", "1.01", amount=2000)

    lines = rank_offer_lines([unknown, confirmed], query())

    assert [line.product_id for line in lines] == ["confirmed", "unknown"]
    assert lines[1].available_qty is None
    assert lines[1].reason_codes == (ReasonCode.STOCK_UNCONFIRMED,)
