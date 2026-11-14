"""Turn a buyer's quantity in L, KG or pieces into sales units of one product."""

import math
from decimal import Decimal

from app.domain.catalog import ContentPerSalesUnit
from app.domain.enums import Unit

# A request in pieces, or with no unit, counts sales units: 1 sales unit is 1 piece,
# unless the content gives the pieces in a pack.
_COUNTED = (None, Unit.PCS)


def fits_request(content: ContentPerSalesUnit | None, unit: Unit | None) -> bool:
    """False when a price per L or KG cannot come from this product's content."""
    if unit in _COUNTED:
        return True

    return content is not None and content.unit is unit


def sales_units_needed(
    quantity: Decimal | None,
    unit: Unit | None,
    content: ContentPerSalesUnit | None,
) -> int:
    """12 L of a 5 x 1 l box is 3 boxes. No quantity is 1 sales unit."""
    # ponytail: an allowedLotSize under 1 counts as 1 (D37), so ceil is enough. Lots over 1
    # (about 640 products) are not rounded up to their multiple yet.
    if quantity is None:
        return 1

    return math.ceil(quantity / _per_sales_unit(unit, content))


def quantity_delivered(
    count: int,
    unit: Unit | None,
    content: ContentPerSalesUnit | None,
) -> Decimal:
    """3 boxes of 5 x 1 l deliver 15 L. 3 packs of 10 eggs deliver 30 pieces."""
    return count * _per_sales_unit(unit, content)


def price_per_unit(
    unit_price: Decimal,
    unit: Unit | None,
    content: ContentPerSalesUnit | None,
) -> Decimal:
    """Not rounded: the ranking sorts on the full value, the screen shows round_money of it."""
    return unit_price / _per_sales_unit(unit, content)


def comparison_unit(unit: Unit | None) -> Unit:
    return Unit.PCS if unit in _COUNTED else unit


def _per_sales_unit(unit: Unit | None, content: ContentPerSalesUnit | None) -> Decimal:
    # A price per litre from kilograms would rank the product on a wrong number.
    if not fits_request(content, unit):
        raise ValueError(f"content {content} does not fit a request in {unit}")

    if unit is not None and content is not None and content.unit is unit:
        return content.value

    return Decimal(1)
