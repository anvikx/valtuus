"""Reject rules: a product with no usable price, stock or size gets no offer line."""

from datetime import datetime

from app.domain.catalog import Product
from app.domain.enums import ReasonCode
from app.domain.offer import Availability, Candidate, OfferQuery, Price, RejectedProduct
from app.domain.reason_text import deadline_text, reason_sentence
from app.domain.units import fits_request


def screen(
    product: Product,
    price: Price | None,
    availability: Availability | None,
    query: OfferQuery,
    now: datetime,
) -> Candidate | RejectedProduct:
    """Reject unusable data and deadlines that have passed before ranking."""
    if price is None:
        return reject(product.product_id, product.name, ReasonCode.NO_PRICE)

    # No schedule line, no date or a zero amount: nothing to deliver.
    if availability is None or availability.available_date is None or not availability.amount:
        return reject(product.product_id, product.name, ReasonCode.NOT_AVAILABLE)

    if availability.closing_time is None:
        return reject(product.product_id, product.name, ReasonCode.DEADLINE_UNKNOWN)

    if availability.closing_time <= now:
        return reject(
            product.product_id,
            product.name,
            ReasonCode.CUTOFF_PASSED,
            closing_time=availability.closing_time,
            deadline=deadline_text(availability.closing_time),
        )

    # 465039 sells in KI (a box of 5 ST). A stock in ST compared with a need in KI is wrong
    # by a factor of 5, so a unit that differs, or is missing, is refused.
    if availability.sales_unit != product.sales_unit:
        return reject(
            product.product_id,
            product.name,
            ReasonCode.UNIT_UNKNOWN,
            stock_unit=availability.sales_unit,
            sales_unit=product.sales_unit,
        )

    if not fits_request(product.content_per_sales_unit, query.unit):
        return reject(product.product_id, product.name, ReasonCode.NO_CONTENT_DATA)

    return Candidate(product=product, price=price, availability=availability)


def reject(
    product_id: str,
    name: str,
    code: ReasonCode,
    *,
    closing_time: datetime | None = None,
    **values: object,
) -> RejectedProduct:
    return RejectedProduct(
        product_id=product_id,
        name=name,
        reason_code=code,
        reason_sentence=reason_sentence(code, **values),
        closing_time=closing_time,
    )
