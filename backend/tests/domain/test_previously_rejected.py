import dataclasses
from datetime import datetime

import pytest

from app.domain.cart import Cart, PricedLine
from app.domain.enums import CartState, Decision, ReasonCode, StockModel
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.previously_rejected import PreviouslyRejected
from tests.adapters import samples

_REJECTED_AT = datetime(2026, 11, 14, 8, 0, tzinfo=samples.NOW.tzinfo)


def _rejected() -> Cart:
    return dataclasses.replace(
        samples.cart("c_0", CartState.REJECTED),
        decided_at=_REJECTED_AT,
        reject_reason="Too much oat milk",
    )


def _line(qty: int = 2, product_id: str = "p_2") -> PricedLine:
    stored = samples.cart().lines[0]
    return PricedLine(
        offer_id=stored.offer_id,
        product_id=product_id,
        name=stored.name,
        qty=qty,
        unit_price=stored.unit_price,
        line_total=stored.unit_price * qty,
        delivery_date=stored.delivery_date,
        closing_time=stored.closing_time,
        substitute_for=None,
        stock_model=StockModel.STOCK,
        available_qty=None,
        needed_qty=qty,
    )


_CONTEXT = PolicyContext(
    mandate=samples.mandate(),
    day_orders=(),
    recent_rejects=(_rejected(),),
    now=samples.NOW,
)
_DENY = CheckResult(
    decision=Decision.DENY,
    reason_code=ReasonCode.PREVIOUSLY_REJECTED,
    sentence='A person rejected this same order at Sat 14 Nov 10:00: "Too much oat milk".',
    line_id=None,
)


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        pytest.param((_line(),), [_DENY], id="same-cart"),
        pytest.param((_line(qty=3),), [], id="other-qty"),
        pytest.param((_line(), _line(product_id="p_3")), [], id="other-lines"),
    ],
)
def test_a_persons_no_holds(lines: tuple[PricedLine, ...], expected: list[CheckResult]) -> None:
    """The agent may not send a rejected cart again. A changed cart is checked from the start."""
    results = PreviouslyRejected().evaluate(lines, _CONTEXT)

    assert results == expected
