from collections.abc import Iterable, Sequence

from app.domain.cart import Cart, CartLine, PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import deadline_text, reason_sentence


class PreviouslyRejected:
    """A person's no holds: the same cart again is refused. A changed cart is a new cart."""

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        rejected = rejected_cart(lines, context.recent_rejects)
        if rejected is None or rejected.decided_at is None:
            return []

        sentence = reason_sentence(
            ReasonCode.PREVIOUSLY_REJECTED,
            rejected_at=deadline_text(rejected.decided_at),
            reject_reason=rejected.reject_reason,
        )
        result = CheckResult(
            decision=Decision.DENY,
            reason_code=ReasonCode.PREVIOUSLY_REJECTED,
            sentence=sentence,
            line_id=None,
        )
        return [result]


def rejected_cart(lines: Iterable[PricedLine], rejects: Iterable[Cart]) -> Cart | None:
    """A rejected cart with the same products, quantities and delivery days."""
    content = _content(lines)
    return next((cart for cart in rejects if _content(cart.lines) == content), None)


def _content(lines: Iterable[PricedLine | CartLine]) -> frozenset[tuple[object, ...]]:
    return frozenset((line.product_id, line.qty, line.delivery_date) for line in lines)
