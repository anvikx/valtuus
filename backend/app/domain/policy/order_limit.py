from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.money import round_money, total_ex_vat
from app.domain.policy.check import CheckResult, PolicyContext


class OrderLimit:
    """The most one cart may cost before a person must approve it."""

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        limit = context.mandate.max_auto_order_value
        if total_ex_vat(line.line_total for line in lines) <= limit:
            return []

        result = CheckResult(
            decision=Decision.HUMAN,
            reason_code=ReasonCode.OVER_AUTO_LIMIT,
            sentence=f"Total is over this agent's {round_money(limit)} EUR limit.",
            line_id=None,
        )
        return [result]
