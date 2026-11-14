from decimal import Decimal

import pytest

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode, StockModel
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.stock_check import StockCheck
from tests.adapters import samples

_PRODUCT_ID = "469363"
_CONTEXT = PolicyContext(
    mandate=samples.mandate(),
    day_orders=(),
    recent_rejects=(),
    now=samples.NOW,
)


def _line(
    qty: int,
    *,
    model: StockModel | None = StockModel.STOCK,
    available: int | None = None,
    needed: int = 1000,
) -> PricedLine:
    return PricedLine(
        offer_id="of_1",
        product_id=_PRODUCT_ID,
        name="Arla lactose free milk 1 l",
        qty=qty,
        unit_price=Decimal("1.01"),
        line_total=Decimal("1.01") * qty,
        delivery_date=samples.DELIVERY_DATE,
        closing_time=samples.NOW,
        substitute_for=None,
        stock_model=model,
        available_qty=available,
        needed_qty=needed,
    )


def _result(decision: Decision, code: ReasonCode, sentence: str) -> CheckResult:
    return CheckResult(decision=decision, reason_code=code, sentence=sentence, line_id=_PRODUCT_ID)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        pytest.param(_line(1000, available=2000), [], id="full-stock"),
        pytest.param(_line(1000, available=1000), [], id="qty-equals-stock"),
        pytest.param(_line(1000), [], id="stock-amount-not-known"),
        pytest.param(
            _line(384, available=384),
            [
                _result(
                    Decision.HUMAN,
                    ReasonCode.PARTIAL_AVAILABILITY,
                    "Only 384 of 1000 in stock.",
                ),
            ],
            id="partial-within-stock",
        ),
        pytest.param(
            _line(1000, available=384),
            [_result(Decision.DENY, ReasonCode.PARTIAL_AVAILABILITY, "Only 384 of 1000 in stock.")],
            id="over-confirmed-stock",
        ),
        pytest.param(
            _line(1000, model=StockModel.TERMINAL),
            [
                _result(
                    Decision.HUMAN,
                    ReasonCode.STOCK_UNCONFIRMED,
                    "Valio Aimo does not confirm the stock of this product.",
                ),
            ],
            id="terminal",
        ),
        pytest.param(
            _line(1000, model=None),
            [
                _result(
                    Decision.HUMAN,
                    ReasonCode.STOCK_UNCONFIRMED,
                    "Valio Aimo does not confirm the stock of this product.",
                ),
            ],
            id="no-logistic-model",
        ),
    ],
)
def test_stock_decides_who_orders_the_line(line: PricedLine, expected: list[CheckResult]) -> None:
    """A partial or unconfirmed quantity always goes to a person; more than the stock is refused."""
    results = StockCheck().evaluate((line,), _CONTEXT)

    assert results == expected
