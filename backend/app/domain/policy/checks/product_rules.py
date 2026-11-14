from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.catalog import Allergens
from app.domain.enums import AllergenStatus, Decision, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import reason_sentence


def _allergens(line: PricedLine, context: PolicyContext) -> Allergens | None:
    product = context.products.get(line.product_id)
    if product is not None:
        return product.allergens

    offer = context.offers.get(line.offer_id)
    if offer is None:
        return None
    return next(
        (item.allergens for item in offer.lines if item.product_id == line.product_id), None
    )


def _allergen_result(line: PricedLine, context: PolicyContext) -> CheckResult | None:
    forbidden = set(context.mandate.forbidden_allergens)
    if not forbidden:
        return None

    allergens = _allergens(line, context)
    if allergens is None or allergens.status is AllergenStatus.UNKNOWN:
        decision = context.mandate.allergen_unknown_policy
        if decision is Decision.AUTO:
            return None
        return CheckResult(
            decision,
            ReasonCode.ALLERGEN_UNKNOWN,
            reason_sentence(ReasonCode.ALLERGEN_UNKNOWN),
            line.product_id,
        )

    blocked = forbidden.intersection(allergens.contains)
    if not blocked:
        return None
    return CheckResult(
        Decision.DENY,
        ReasonCode.FORBIDDEN_ALLERGEN,
        reason_sentence(ReasonCode.FORBIDDEN_ALLERGEN, allergens=", ".join(sorted(blocked))),
        line.product_id,
    )


class Allergen:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        return [result for line in lines if (result := _allergen_result(line, context)) is not None]


class RequiredAttributes:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        results = []
        for line in lines:
            product = context.products.get(line.product_id)
            attributes = () if product is None else product.attributes
            missing = set(context.mandate.required_attributes) - set(attributes)
            if missing:
                results.append(
                    CheckResult(
                        Decision.DENY,
                        ReasonCode.MISSING_ATTRIBUTE,
                        reason_sentence(
                            ReasonCode.MISSING_ATTRIBUTE, attributes=", ".join(sorted(missing))
                        ),
                        line.product_id,
                    )
                )
        return results


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
                        brand=brand or "unknown",
                        preferred=", ".join(context.mandate.preferred_brands),
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
                    product=line.name,
                    requested=line.substitute_for.name,
                ),
                line.product_id,
            )
            for line in lines
            if line.substitute_for is not None
        ]
