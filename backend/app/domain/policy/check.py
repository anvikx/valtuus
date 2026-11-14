from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.domain.cart import Cart, PricedLine
from app.domain.catalog import Product
from app.domain.enums import Decision, ReasonCode
from app.domain.mandate import Mandate
from app.domain.order import Order


@dataclass(frozen=True)
class PolicyContext:
    mandate: Mandate
    day_orders: tuple[Order, ...]
    recent_rejects: tuple[Cart, ...]
    now: datetime
    # By product id. A line with no entry has no product data.
    products: Mapping[str, Product] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    decision: Decision
    reason_code: ReasonCode
    sentence: str
    # None when the reason is about the whole cart, not one line.
    line_id: str | None


class PolicyCheck(Protocol):
    """One dimension of the envelope. Pure, so a preview gives the same answer as the order."""

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        """Takes lines, not a Cart: the cart is built from the result, so it cannot be an input."""
        ...
