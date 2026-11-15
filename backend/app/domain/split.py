"""Cover a quantity that no single offer line can, with several products for one date."""

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import ReasonCode
from app.domain.offer import OfferLine, OfferQuery, ProposedSplit, SplitLine
from app.domain.units import quantity_delivered, sales_units_needed

Contents = Mapping[str, ContentPerSalesUnit | None]

_PARTIAL = (ReasonCode.PARTIAL_AVAILABILITY,)
_OUTSIDE_PREFERENCE = (ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,)
_LATE = ReasonCode.DELIVERY_AFTER_DEADLINE


def propose_split(
    lines: Sequence[OfferLine],
    contents: Contents,
    query: OfferQuery,
    preferred_brands: Sequence[str],
) -> ProposedSplit | None:
    """Lines are in rank order. Substitute lines stay out: another rule offers those.

    `contents` gives each product's content per sales unit, because the rest of the need
    is worked in the requested unit and converted per product (12 L is 12 cartons of 1 l
    but 3 boxes of 4 l).
    """
    quantity = query.quantity
    if quantity is None:
        return None

    own = [line for line in lines if line.substitute_for is None]
    group_a = [line for line in own if not line.reason_codes]
    preferred = {_brand_key(brand) for brand in preferred_brands}
    split = _backfill_preferred(own, group_a, contents, query, quantity, preferred)
    if split is not None:
        return split

    # With a group A line, rank 1 covers the request.
    if group_a:
        return None

    return _stocked_lines(own, contents, query, quantity)


def _backfill_preferred(
    lines: Sequence[OfferLine],
    group_a: Sequence[OfferLine],
    contents: Contents,
    query: OfferQuery,
    quantity: Decimal,
    preferred: set[str],
) -> ProposedSplit | None:
    """Rule 1: all stock of a short preferred line, the rest from the best group A line."""
    partial = _short_preferred(lines, preferred)
    if partial is None:
        return None

    # One delivery date: a product on another date cannot share the delivery.
    fillers = [line for line in group_a if line.available_date == partial.available_date]
    if not fillers:
        return None

    filler = fillers[0]
    rest = _rest(query, quantity, partial, contents)
    qty = sales_units_needed(rest, query.unit, contents[filler.product_id])
    outside = () if _is_preferred(filler, preferred) else _OUTSIDE_PREFERENCE
    return ProposedSplit(
        lines=(
            SplitLine(partial.product_id, _stock(partial), _PARTIAL),
            SplitLine(filler.product_id, qty, outside),
        ),
        unfilled_qty=0,
    )


def _short_preferred(lines: Sequence[OfferLine], preferred: set[str]) -> OfferLine | None:
    """The cheapest preferred line, when its confirmed stock is below its need and on time."""
    brand_lines = [line for line in lines if _is_preferred(line, preferred)]
    if not brand_lines:
        return None

    cheapest = min(brand_lines, key=lambda line: (line.comparison_price.value, line.rank))
    if cheapest.available_qty is None or cheapest.available_qty >= cheapest.sales_units_needed:
        return None

    return None if _LATE in cheapest.reason_codes else cheapest


def _stocked_lines(
    lines: Sequence[OfferLine],
    contents: Contents,
    query: OfferQuery,
    quantity: Decimal,
) -> ProposedSplit | None:
    """Rule 2: no line has full cover, so take confirmed stock in rank order until it is met."""
    usable = [line for line in lines if line.available_qty and _LATE not in line.reason_codes]
    taken: list[SplitLine] = []
    rest = quantity
    for line in usable:
        if rest <= 0:
            break

        # The date of the first line taken is the date of the delivery.
        if line.available_date != usable[0].available_date:
            continue

        content = contents[line.product_id]
        qty = min(_stock(line), sales_units_needed(rest, query.unit, content))
        taken.append(SplitLine(line.product_id, qty, line.reason_codes))
        rest -= quantity_delivered(qty, query.unit, content)

    if not taken:
        return None

    return ProposedSplit(lines=tuple(taken), unfilled_qty=max(0, math.ceil(rest)))


def _rest(query: OfferQuery, quantity: Decimal, partial: OfferLine, contents: Contents) -> Decimal:
    delivered = quantity_delivered(_stock(partial), query.unit, contents[partial.product_id])
    return quantity - delivered


def _stock(line: OfferLine) -> int:
    # Callers pick lines with a confirmed stock count.
    return line.available_qty or 0


def _is_preferred(line: OfferLine, preferred: set[str]) -> bool:
    return line.brand is not None and _brand_key(line.brand) in preferred


def _brand_key(brand: str) -> str:
    # Same match as the Brand policy check, so the split and the cart decision agree.
    return brand.casefold()
