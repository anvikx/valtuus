from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode, StockModel
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import reason_sentence


class StockCheck:
    """A partial or unconfirmed quantity goes to a person. More than the stock is refused."""

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        return [result for line in lines if (result := _stock_result(line)) is not None]


def _stock_result(line: PricedLine) -> CheckResult | None:
    if line.stock_model is not StockModel.STOCK:
        return _result(line, Decision.HUMAN, ReasonCode.STOCK_UNCONFIRMED)

    # None: Valio Aimo confirms stock but sent no amount, which counts as in stock.
    available = line.available_qty
    if available is None:
        return None

    if line.qty > available:
        return _result(line, Decision.DENY, ReasonCode.PARTIAL_AVAILABILITY, needed_qty=line.qty)

    if available < line.needed_qty:
        return _result(
            line, Decision.HUMAN, ReasonCode.PARTIAL_AVAILABILITY, needed_qty=line.needed_qty
        )

    return None


def _result(line: PricedLine, decision: Decision, code: ReasonCode, **values: int) -> CheckResult:
    return CheckResult(
        decision=decision,
        reason_code=code,
        sentence=reason_sentence(code, available_qty=line.available_qty, **values),
        line_id=line.product_id,
    )
