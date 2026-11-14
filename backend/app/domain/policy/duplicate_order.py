from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from app.domain.cart import PricedLine
from app.domain.constants import DUPLICATE_WINDOW_MINUTES
from app.domain.enums import Decision, ReasonCode
from app.domain.order import Order
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import reason_sentence

_WINDOW = timedelta(minutes=DUPLICATE_WINDOW_MINUTES)


class DuplicateOrder:
    """A line that repeats a recent order waits for a person, so a retry cannot order twice."""

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        results = []
        for line in lines:
            order = duplicate_order(line, context.day_orders, context.now)
            if order is None:
                continue

            sentence = reason_sentence(ReasonCode.DUPLICATE_ORDER, order_id=order.order_id)
            results.append(
                CheckResult(
                    decision=Decision.HUMAN,
                    reason_code=ReasonCode.DUPLICATE_ORDER,
                    sentence=sentence,
                    line_id=line.product_id,
                )
            )

        return results


def duplicate_order(line: PricedLine, orders: Iterable[Order], now: datetime) -> Order | None:
    """An order placed inside the window with the same product, qty and delivery day."""
    key = (line.product_id, line.qty, line.delivery_date)
    for order in orders:
        if now - order.placed_at >= _WINDOW:
            continue

        if any(
            (placed.product_id, placed.qty, placed.delivery_date) == key for placed in order.lines
        ):
            return order

    return None
