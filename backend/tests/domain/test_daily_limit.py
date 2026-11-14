import dataclasses
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.order import Order
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.daily_limit import DailyLimit
from tests.adapters import samples

_DAY = samples.DELIVERY_DATE
_NEXT_DAY = _DAY + timedelta(days=1)
_DAY_LIMIT = Decimal("500.00")
_APPROVER = "hotel-1-main"


def _line(total: str, day: date = _DAY) -> PricedLine:
    return PricedLine(
        offer_id="of_1",
        product_id="464306",
        name="Oat milk 1 l",
        qty=1,
        unit_price=Decimal(total),
        line_total=Decimal(total),
        delivery_date=day,
        closing_time=samples.NOW,
        substitute_for=None,
    )


def _order(total: str, day: date = _DAY, approved_by: str | None = None) -> Order:
    order = samples.order(order_id=f"o_{total}_{day}", delivery_date=day)
    lines = tuple(dataclasses.replace(line, line_total=Decimal(total)) for line in order.lines)
    return dataclasses.replace(order, lines=lines, approved_by=approved_by)


def _context(*day_orders: Order) -> PolicyContext:
    mandate = dataclasses.replace(
        samples.mandate(),
        max_auto_value_per_delivery_date=_DAY_LIMIT,
    )
    return PolicyContext(mandate=mandate, day_orders=day_orders, recent_rejects=(), now=samples.NOW)


def test_small_carts_that_pass_the_day_limit_together_wait():
    """An agent must not split one large order into small carts that each pass alone."""
    results = DailyLimit().evaluate((_line("101.00"),), _context(_order("400.00")))

    assert results == [
        CheckResult(
            decision=Decision.HUMAN,
            reason_code=ReasonCode.OVER_DAILY_AUTO_LIMIT,
            sentence="Automatic orders for Fri 20 Nov would be 501.00 EUR, over the "
            "500.00 EUR daily limit.",
            line_id=None,
        ),
    ]


@pytest.mark.parametrize(
    ("cart_total", "placed"),
    [
        pytest.param("100.00", _order("400.00"), id="exactly-the-limit"),
        pytest.param("101.00", _order("400.00", approved_by=_APPROVER), id="approved-order"),
        pytest.param("101.00", _order("400.00", day=_NEXT_DAY), id="other-date"),
    ],
)
def test_only_auto_orders_on_the_same_date_count(cart_total, placed):
    """A person approved the other order, or it is for another day, so the agent spent less."""
    assert DailyLimit().evaluate((_line(cart_total),), _context(placed)) == []


def test_each_delivery_date_has_its_own_limit():
    """300 EUR on 2 dates is 600 EUR in the cart, but no date is over 500 EUR."""
    lines = (_line("300.00"), _line("300.00", day=_NEXT_DAY))

    assert DailyLimit().evaluate(lines, _context()) == []
