from decimal import Decimal

import pytest

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import ReasonCode, Unit
from app.domain.offer import Candidate
from app.domain.screening import screen
from tests.fakes.offer_data import price, product, query, stock

_BOX_OF_FIVE = "465039"


def test_a_box_with_stock_counted_in_pieces_is_refused() -> None:
    """465039 sells in KI (5 ST). 10 ST of stock read as 10 boxes would promise 50 pieces."""
    box = product(_BOX_OF_FIVE, sales_unit="KI")

    result = screen(box, price(_BOX_OF_FIVE), stock(_BOX_OF_FIVE, amount=10), query())

    assert result.reason_code is ReasonCode.UNIT_UNKNOWN
    assert result.reason_sentence == "The stock is counted in ST, but the product is sold in KI."


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(ContentPerSalesUnit(Decimal(1), Unit.KG), id="content in KG"),
        pytest.param(None, id="no content"),
    ],
)
def test_a_request_in_litres_needs_content_in_litres(content) -> None:
    """Else the price per litre would come from kilograms, or from nothing."""
    result = screen(product(content=content), price(), stock(), query(unit=Unit.L))

    assert result.reason_code is ReasonCode.NO_CONTENT_DATA
    assert result.reason_sentence == "The size of this product is not in the data."


def test_a_request_in_pieces_needs_no_content() -> None:
    result = screen(product(content=None), price(), stock(), query(quantity="4", unit=Unit.PCS))

    assert isinstance(result, Candidate)


@pytest.mark.parametrize(
    ("live_price", "live_stock", "code"),
    [
        pytest.param(None, stock(), ReasonCode.NO_PRICE, id="no price"),
        pytest.param(price(), None, ReasonCode.NOT_AVAILABLE, id="no stock line"),
        pytest.param(price(), stock(amount=0), ReasonCode.NOT_AVAILABLE, id="amount 0"),
        pytest.param(price(), stock(available_date=None), ReasonCode.NOT_AVAILABLE, id="no date"),
        pytest.param(price(), stock(sales_unit=None), ReasonCode.UNIT_UNKNOWN, id="no unit"),
    ],
)
def test_missing_live_data_is_a_reject_with_a_reason(live_price, live_stock, code) -> None:
    """An offer line on a guessed price or stock would be a promise nobody made."""
    result = screen(product(), live_price, live_stock, query())

    assert result.reason_code is code
    assert result.reason_sentence
