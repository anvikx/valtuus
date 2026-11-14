from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.cart import Cart, PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.mandate import Mandate
from app.domain.order import Order


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason_codes: tuple[ReasonCode, ...]
    line_reason_codes: tuple[tuple[ReasonCode, ...], ...]


def decide(
    lines: Sequence[PricedLine],
    mandate: Mandate,
    day_orders: Sequence[Order],
    recent_rejects: Sequence[Cart],
    now: datetime,
) -> PolicyResult:
    """AUTO, HUMAN or DENY by the decision table. Reads nothing, so preview is the same call.

    Takes lines, not a Cart: the cart is built from this result, so it cannot be an input.
    """
    raise NotImplementedError("PolicyEngine.decide")
