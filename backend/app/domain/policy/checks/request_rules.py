from collections.abc import Sequence
from decimal import Decimal

from app.domain.cart import PricedLine
from app.domain.constants import MAX_OVER_REQUEST_PERCENT
from app.domain.enums import Decision, ReasonCode
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.reason_text import day_text, reason_sentence
from app.domain.units import fits_request, quantity_delivered

_MAX_REQUEST_FACTOR = Decimal(1) + Decimal(MAX_OVER_REQUEST_PERCENT) / Decimal(100)


class Delivery:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        results = []
        for line in lines:
            offer = context.offers.get(line.offer_id)
            deadline = None if offer is None else offer.requested.deliver_by
            if deadline is None or line.delivery_date <= deadline:
                continue
            results.append(
                CheckResult(
                    Decision.HUMAN,
                    ReasonCode.DELIVERY_AFTER_DEADLINE,
                    reason_sentence(
                        ReasonCode.DELIVERY_AFTER_DEADLINE,
                        available_date=day_text(line.delivery_date),
                        deliver_by=day_text(deadline),
                    ),
                    line.product_id,
                )
            )
        return results


class RequestQuantity:
    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        results = []
        for line in lines:
            offer = context.offers.get(line.offer_id)
            if offer is None or offer.requested.quantity is None:
                continue

            product = context.products.get(line.product_id)
            content = None if product is None else product.content_per_sales_unit
            requested = offer.requested
            if not fits_request(content, requested.unit):
                results.append(
                    CheckResult(
                        Decision.DENY,
                        ReasonCode.NO_CONTENT_DATA,
                        reason_sentence(ReasonCode.NO_CONTENT_DATA),
                        line.product_id,
                    )
                )
                continue

            delivered = quantity_delivered(line.qty, requested.unit, content)
            if delivered <= requested.quantity * _MAX_REQUEST_FACTOR:
                continue
            results.append(
                CheckResult(
                    Decision.HUMAN,
                    ReasonCode.QUANTITY_OVER_REQUEST,
                    reason_sentence(
                        ReasonCode.QUANTITY_OVER_REQUEST,
                        cart_qty=f"{delivered} {requested.unit or 'sales units'}",
                        requested_qty=f"{requested.quantity} {requested.unit or 'sales units'}",
                    ),
                    line.product_id,
                )
            )
        return results
