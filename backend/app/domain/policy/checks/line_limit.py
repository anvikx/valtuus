from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import money_text, reason_sentence


class LineLimit:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        limit = context.mandate.max_line_value
        if limit is None:
            return []

        return [
            CheckResult(
                Decision.HUMAN,
                ReasonCode.OVER_LINE_LIMIT,
                reason_sentence(
                    ReasonCode.OVER_LINE_LIMIT,
                    line_total=money_text(line.line_total),
                    limit=money_text(limit),
                ),
                line.product_id,
            )
            for line in lines
            if line.line_total > limit
        ]
