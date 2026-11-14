from collections.abc import Sequence

from app.domain.cart import PricedLine
from app.domain.enums import Decision, ReasonCode
from app.domain.money import total_ex_vat
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import day_text, money_text, reason_sentence


class DailyLimit:
    """The most the agent may order alone for one delivery date, over all its carts.

    Only AUTO orders count: a person approved the others. Checkout holds the day lock while
    it runs this check, so two parallel checkouts cannot both pass.
    """

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        limit = context.mandate.max_auto_value_per_delivery_date
        placed = [
            line
            for order in context.day_orders
            if order.approved_by is None
            for line in order.lines
        ]
        results = []
        for day in sorted({line.delivery_date for line in lines}):
            day_total = total_ex_vat(
                [
                    *(line.line_total for line in placed if line.delivery_date == day),
                    *(line.line_total for line in lines if line.delivery_date == day),
                ]
            )
            if day_total <= limit:
                continue

            sentence = reason_sentence(
                ReasonCode.OVER_DAILY_AUTO_LIMIT,
                delivery_date=day_text(day),
                day_total=money_text(day_total),
                limit=money_text(limit),
            )
            results.append(
                CheckResult(Decision.HUMAN, ReasonCode.OVER_DAILY_AUTO_LIMIT, sentence, None)
            )

        return results
