from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.domain.cart import PricedLine
from app.domain.enums import Decision
from app.domain.policy.check import CheckResult, PolicyCheck, PolicyContext

_STRICTNESS = (Decision.AUTO, Decision.HUMAN, Decision.DENY)


def strictest(decisions: Iterable[Decision]) -> Decision:
    return max(decisions, key=_STRICTNESS.index, default=Decision.AUTO)


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    # Every HUMAN and DENY result, so the person sees all problems at once.
    reasons: tuple[CheckResult, ...]


class PolicyEngine:
    """A new risk is a new check in the list. The engine does not change."""

    def __init__(self, checks: Sequence[PolicyCheck]) -> None:
        self._checks = tuple(checks)

    def decide(self, lines: Sequence[PricedLine], context: PolicyContext) -> PolicyResult:
        results = [result for check in self._checks for result in check.evaluate(lines, context)]
        reasons = tuple(result for result in results if result.decision is not Decision.AUTO)
        return PolicyResult(
            decision=strictest(reason.decision for reason in reasons),
            reasons=reasons,
        )
