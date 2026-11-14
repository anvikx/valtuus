from dataclasses import replace
from datetime import UTC, timedelta
from decimal import Decimal

import pytest

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import ReasonCode, StockModel, Unit
from app.domain.offer import Candidate
from app.domain.screening import screen
from tests.fakes.offer_data import NOW, price, product, query, stock

_BOX_OF_FIVE = "465039"


def test_a_box_with_stock_counted_in_pieces_is_refused() -> None:
    """465039 sells in KI (5 ST). 10 ST of stock read as 10 boxes would promise 50 pieces."""
    box = product(_BOX_OF_FIVE, sales_unit="KI")

    result = screen(box, price(_BOX_OF_FIVE), stock(_BOX_OF_FIVE, amount=10), query(), NOW)

    assert result.reason_code is ReasonCode.UNIT_UNKNOWN
    assert result.reason_sentence == "The stock is counted in ST, but the product is sold in KI."


@pytest.mark.parametrize(
    ("unit", "content"),
    [
        pytest.param(Unit.L, ContentPerSalesUnit(Decimal(1), Unit.KG), id="L from KG"),
        pytest.param(Unit.L, None, id="L without content"),
        pytest.param(Unit.KG, None, id="KG without content"),
    ],
)
def test_a_measured_request_needs_matching_content(unit, content) -> None:
    """Else the price per litre would come from kilograms, or from nothing."""
    result = screen(product(content=content), price(), stock(), query(unit=unit), NOW)

    assert result.reason_code is ReasonCode.NO_CONTENT_DATA
    assert result.reason_sentence == "The size of this product is not in the data."


def test_a_request_in_pieces_needs_no_content() -> None:
    result = screen(
        product(content=None),
        price(),
        stock(),
        query(quantity="4", unit=Unit.PCS),
        NOW,
    )

    assert isinstance(result, Candidate)


@pytest.mark.parametrize(
    ("live_price", "live_stock", "code"),
    [
        pytest.param(None, stock(), ReasonCode.NO_PRICE, id="no price"),
        pytest.param(price(), None, ReasonCode.NOT_AVAILABLE, id="no stock line"),
        pytest.param(price(), stock(amount=0), ReasonCode.NOT_AVAILABLE, id="amount 0"),
        pytest.param(price(), stock(amount=None), ReasonCode.NOT_AVAILABLE, id="null amount"),
        pytest.param(price(), stock(available_date=None), ReasonCode.NOT_AVAILABLE, id="no date"),
        pytest.param(price(), stock(sales_unit=None), ReasonCode.UNIT_UNKNOWN, id="no unit"),
        pytest.param(
            price(),
            replace(stock(), closing_time=None),
            ReasonCode.DEADLINE_UNKNOWN,
            id="no deadline",
        ),
    ],
)
def test_missing_live_data_is_a_reject_with_a_reason(live_price, live_stock, code) -> None:
    """An offer line on a guessed price or stock would be a promise nobody made."""
    result = screen(product(), live_price, live_stock, query(), NOW)

    assert result.reason_code is code
    assert result.reason_sentence


@pytest.mark.parametrize("model", [StockModel.STOCK, StockModel.TERMINAL, None])
def test_zero_stock_is_unavailable_for_every_model(model) -> None:
    result = screen(product(), price(), stock(amount=0, model=model), query(), NOW)

    assert result.reason_code is ReasonCode.NOT_AVAILABLE
    assert result.reason_sentence == "Valio Aimo cannot deliver this product."


@pytest.mark.parametrize("offset", [-1, 0, 1], ids=["passed", "at deadline", "before deadline"])
def test_cutoff_uses_the_current_instant_and_returns_the_deadline(offset) -> None:
    """UTC upstream times and Helsinki clock times must agree at the boundary."""
    closing = (NOW + timedelta(seconds=offset)).astimezone(UTC)
    availability = replace(stock(), closing_time=closing)

    result = screen(product(), price(), availability, query(), NOW)

    if offset > 0:
        assert isinstance(result, Candidate)
    else:
        assert result.reason_code is ReasonCode.CUTOFF_PASSED
        assert result.closing_time == closing
        assert result.reason_sentence == (
            "The order deadline Sat 14 Nov 15:39 has passed. Get new offers."
            if offset == 0
            else "The order deadline Sat 14 Nov 15:38 has passed. Get new offers."
        )
