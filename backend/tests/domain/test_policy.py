import dataclasses
from collections.abc import Sequence
from decimal import Decimal

import pytest

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode, StockModel
from app.domain.money import line_total
from app.domain.policy.auto_order_switch import AutoOrderSwitch
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from tests.adapters import samples

_OAT_MILK_PRICE = Decimal("1.01")
_CONTEXT = PolicyContext(
    mandate=dataclasses.replace(samples.mandate(), max_auto_order_value=Decimal(500)),
    day_orders=(),
    recent_rejects=(),
    now=samples.NOW,
)


def _lines(qty: int, unit_price: Decimal = _OAT_MILK_PRICE) -> tuple[PricedLine, ...]:
    line = PricedLine(
        offer_id="of_1",
        product_id="464306",
        name="Oat milk 1 l",
        qty=qty,
        unit_price=unit_price,
        line_total=line_total(qty, unit_price),
        delivery_date=samples.DELIVERY_DATE,
        closing_time=samples.NOW,
        substitute_for=None,
        stock_model=StockModel.STOCK,
        available_qty=None,
        needed_qty=1,
    )
    return (line,)


class _Fixed:
    def __init__(self, *results: CheckResult) -> None:
        self._results = list(results)

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        return self._results


def _result(decision: Decision, code: ReasonCode) -> CheckResult:
    return CheckResult(decision=decision, reason_code=code, sentence=code, line_id=None)


def test_large_cart_waits_for_a_human():
    """1,000 l at 1.01 EUR is 1,010.00 EUR, over the 500 EUR limit, so a person must approve."""
    result = PolicyEngine((OrderLimit(),)).decide(_lines(1000), _CONTEXT)

    assert result.decision is Decision.HUMAN
    assert result.reasons == (
        CheckResult(
            decision=Decision.HUMAN,
            reason_code=ReasonCode.OVER_AUTO_LIMIT,
            sentence="1,010.00 EUR is over the 500.00 EUR limit.",
            line_id=None,
        ),
    )


@pytest.mark.parametrize(
    ("qty", "unit_price"),
    [
        pytest.param(20, _OAT_MILK_PRICE, id="20-l"),
        pytest.param(1, Decimal(500), id="exactly-the-limit"),
    ],
)
def test_cart_within_limit_is_auto(qty, unit_price):
    """The limit is the most an agent may spend alone, so a total equal to it is still AUTO."""
    result = PolicyEngine((OrderLimit(),)).decide(_lines(qty, unit_price), _CONTEXT)

    assert result.decision is Decision.AUTO
    assert result.reasons == ()


def test_strictest_decision_wins_and_every_reason_is_kept():
    """The person sees all problems at once, not one per round trip."""
    human = _result(Decision.HUMAN, ReasonCode.OVER_AUTO_LIMIT)
    deny = _result(Decision.DENY, ReasonCode.FORBIDDEN_ALLERGEN)
    engine = PolicyEngine((_Fixed(human), _Fixed(deny), _Fixed()))

    result = engine.decide(_lines(1), _CONTEXT)

    assert result.decision is Decision.DENY
    assert result.reasons == (human, deny)


def test_auto_results_are_not_reasons():
    """An AUTO result explains nothing to the person, so it must not show as a reason."""
    engine = PolicyEngine((_Fixed(_result(Decision.AUTO, ReasonCode.OVER_AUTO_LIMIT)),))

    result = engine.decide(_lines(1), _CONTEXT)

    assert result.decision is Decision.AUTO
    assert result.reasons == ()


def test_small_cart_waits_for_a_human_when_automatic_orders_are_off():
    """Off is the default, so a new buyer's agent can never spend money alone."""
    context = dataclasses.replace(
        _CONTEXT,
        mandate=dataclasses.replace(_CONTEXT.mandate, can_auto_order=False),
    )

    result = PolicyEngine((AutoOrderSwitch(), OrderLimit())).decide(_lines(20), context)

    assert result.decision is Decision.HUMAN
    assert result.reasons == (
        CheckResult(
            decision=Decision.HUMAN,
            reason_code=ReasonCode.AUTO_ORDERS_OFF,
            sentence="Automatic orders are off.",
            line_id=None,
        ),
    )


def test_switch_on_leaves_the_decision_to_the_limits():
    """With the switch on, a 20.20 EUR cart under the 500 EUR limit is still AUTO."""
    result = PolicyEngine((AutoOrderSwitch(), OrderLimit())).decide(_lines(20), _CONTEXT)

    assert result.decision is Decision.AUTO
    assert result.reasons == ()
