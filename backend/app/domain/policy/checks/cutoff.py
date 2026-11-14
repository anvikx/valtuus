from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import deadline_text, reason_sentence


class Cutoff:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        return [
            CheckResult(
                Decision.DENY,
                ReasonCode.CUTOFF_PASSED,
                reason_sentence(
                    ReasonCode.CUTOFF_PASSED, deadline=deadline_text(line.closing_time)
                ),
                line.product_id,
            )
            for line in lines
            if context.now >= line.closing_time
        ]
