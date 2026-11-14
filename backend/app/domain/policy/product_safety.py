from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.cart import PricedLine
from app.domain.catalog import Product
from app.domain.enums import AllergenStatus, Decision, ReasonCode
from app.domain.mandate import Mandate
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import reason_sentence


@dataclass(frozen=True)
class RuleBreak:
    decision: Decision
    reason_code: ReasonCode
    attribute: str | None = None


class ProductSafety:
    """The agent can order a product it never searched for, so search cannot hold the rules."""

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        return [
            _result(line, rule_break)
            for line in lines
            for rule_break in _breaks(context.products.get(line.product_id), context.mandate)
        ]


def allergen_break(product: Product | None, mandate: Mandate) -> RuleBreak | None:
    """None for a product not in the catalog: its allergens are not known."""
    forbidden = set(mandate.forbidden_allergens)
    if not forbidden:
        return None

    if product is not None:
        if forbidden & set(product.allergens.contains):
            return RuleBreak(Decision.DENY, ReasonCode.FORBIDDEN_ALLERGEN)
        if product.allergens.status is AllergenStatus.KNOWN:
            return None

    if mandate.allergen_unknown_policy is Decision.AUTO:
        return None
    return RuleBreak(mandate.allergen_unknown_policy, ReasonCode.ALLERGEN_UNKNOWN)


def _attribute_breaks(product: Product | None, mandate: Mandate) -> list[RuleBreak]:
    attributes = () if product is None else product.attributes
    return [
        RuleBreak(Decision.DENY, ReasonCode.MISSING_ATTRIBUTE, code)
        for code in mandate.required_attributes
        if code not in attributes
    ]


def _breaks(product: Product | None, mandate: Mandate) -> list[RuleBreak]:
    allergen = allergen_break(product, mandate)
    return [*([allergen] if allergen else []), *_attribute_breaks(product, mandate)]


def _result(line: PricedLine, rule_break: RuleBreak) -> CheckResult:
    return CheckResult(
        decision=rule_break.decision,
        reason_code=rule_break.reason_code,
        sentence=reason_sentence(rule_break.reason_code, attribute=rule_break.attribute),
        line_id=line.product_id,
    )
