import dataclasses
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.cart import PricedLine
from app.domain.constants import DUPLICATE_WINDOW_MINUTES
from app.domain.enums import Decision, ReasonCode, StockModel
from app.domain.order import Order
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.duplicate_order import DuplicateOrder
from tests.adapters import samples

_PRODUCT_ID = "p_2"
_QTY = 2
_WINDOW = timedelta(minutes=DUPLICATE_WINDOW_MINUTES)


def _line(product_id: str = _PRODUCT_ID, qty: int = _QTY, day=samples.DELIVERY_DATE) -> PricedLine:
    return PricedLine(
        offer_id="of_1",
        product_id=product_id,
        name="Oat milk 1 l",
        qty=qty,
        unit_price=Decimal("1.01"),
        line_total=Decimal("1.01") * qty,
        delivery_date=day,
        closing_time=samples.NOW,
        substitute_for=None,
        stock_model=StockModel.STOCK,
        available_qty=None,
        needed_qty=qty,
    )


def _order(placed_ago: timedelta = timedelta(minutes=5)) -> Order:
    return dataclasses.replace(samples.order("o_9"), placed_at=samples.NOW - placed_ago)


def _context(*orders: Order) -> PolicyContext:
    return PolicyContext(
        mandate=samples.mandate(),
        day_orders=orders,
        recent_rejects=(),
        now=samples.NOW,
    )


_DUPLICATE = CheckResult(
    decision=Decision.HUMAN,
    reason_code=ReasonCode.DUPLICATE_ORDER,
    sentence="Possible duplicate: order o_9 has the same product, quantity and delivery day.",
    line_id=_PRODUCT_ID,
)


@pytest.mark.parametrize(
    ("line", "order", "expected"),
    [
        pytest.param(_line(), _order(), [_DUPLICATE], id="same-line-inside-window"),
        pytest.param(_line(qty=3), _order(), [], id="other-qty"),
        pytest.param(_line(product_id="p_3"), _order(), [], id="other-product"),
        pytest.param(
            _line(day=samples.DELIVERY_DATE + timedelta(days=1)), _order(), [], id="other-day"
        ),
        pytest.param(_line(), _order(placed_ago=_WINDOW), [], id="window-ended"),
    ],
)
def test_same_order_again_waits_for_a_person(
    line: PricedLine, order: Order, expected: list[CheckResult]
) -> None:
    """An agent that retries with a new key must not order the same goods twice by itself."""
    results = DuplicateOrder().evaluate((line,), _context(order))

    assert results == expected
