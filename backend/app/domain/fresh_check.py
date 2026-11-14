"""After an offer's stock snapshot runs out, a cart line holds only if a fresh read agrees."""

from app.domain.cart import CartLine
from app.domain.offer import Availability, Price
from app.domain.ranking import counted_stock


def line_holds(line: CartLine, price: Price | None, availability: Availability | None) -> bool:
    """Same price, same delivery date, and stock for the qty. Missing data fails closed."""
    if price is None or price.unit_price != line.unit_price:
        return False

    # A cart is only made when the price covers the delivery date; it must still cover it.
    if not price.valid_from <= line.delivery_date <= price.valid_to:
        return False

    if availability is None or availability.is_sales_blocked or not availability.amount:
        return False

    if availability.available_date != line.delivery_date:
        return False

    # Stock with no count passed the offer as STOCK_UNCONFIRMED, so it is judged the same now.
    counted = counted_stock(availability)
    return counted is None or counted >= line.qty
