from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, EnvelopeMode, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import reason_sentence


class KnownProduct:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        if context.mandate.envelope_mode is EnvelopeMode.OFF:
            return []

        return [
            CheckResult(
                Decision.HUMAN,
                ReasonCode.NEW_PRODUCT,
                reason_sentence(ReasonCode.NEW_PRODUCT, product=line.name),
                line.product_id,
            )
            for line in lines
            if line.product_id not in context.baseline
        ]


class Quantity:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        if context.mandate.envelope_mode is EnvelopeMode.OFF:
            return []

        results = []
        for line in lines:
            baseline = context.baseline.get(line.product_id)
            factor = context.mandate.quantity_factor
            if baseline is None or line.qty <= baseline.max_confirmed_quantity * factor:
                continue

            results.append(
                CheckResult(
                    Decision.HUMAN,
                    ReasonCode.QUANTITY_UNUSUAL,
                    reason_sentence(
                        ReasonCode.QUANTITY_UNUSUAL,
                        quantity=f"{line.qty:,}",
                        baseline=f"{baseline.max_confirmed_quantity:,}",
                        factor=f"{factor:g}",
                    ),
                    line.product_id,
                )
            )
        return results
