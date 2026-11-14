from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import reason_sentence


class Brand:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        preferred = {brand.casefold() for brand in context.mandate.preferred_brands}
        if not preferred:
            return []

        results = []
        for line in lines:
            product = context.products.get(line.product_id)
            brand = None if product is None else product.brand
            if brand is not None and brand.casefold() in preferred:
                continue
            results.append(
                CheckResult(
                    Decision.HUMAN,
                    ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,
                    reason_sentence(
                        ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,
                        substitute=brand or "unknown",
                    ),
                    line.product_id,
                )
            )
        return results


class Substitute:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        return [
            CheckResult(
                Decision.HUMAN,
                ReasonCode.SUBSTITUTE_FOR_REQUESTED,
                reason_sentence(
                    ReasonCode.SUBSTITUTE_FOR_REQUESTED,
                    substitute=line.name,
                    requested=line.substitute_for.name,
                ),
                line.product_id,
            )
            for line in lines
            if line.substitute_for is not None
        ]
