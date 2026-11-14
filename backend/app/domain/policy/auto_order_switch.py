from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext


class AutoOrderSwitch:
    """While the main user has not turned on automatic orders, a person approves every cart."""

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        if context.mandate.can_auto_order:
            return []

        result = CheckResult(
            decision=Decision.HUMAN,
            reason_code=ReasonCode.AUTO_ORDERS_OFF,
            sentence="Automatic orders are off.",
            line_id=None,
        )
        return [result]
