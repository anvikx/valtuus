"""One sentence per reason code. The page, the agent's reply and the audit use the same text."""

from datetime import date
from types import MappingProxyType

from app.domain.enums import ReasonCode

REASON_TEXT = MappingProxyType(
    {
        ReasonCode.PRODUCT_NOT_FOUND: "This product is not in the Valio Aimo catalog.",
        ReasonCode.NO_PRICE: "Valio Aimo has no price for this product.",
        ReasonCode.NOT_AVAILABLE: "Valio Aimo cannot deliver this product.",
        ReasonCode.DEADLINE_UNKNOWN: "The order deadline of this product is not known.",
        ReasonCode.UNIT_UNKNOWN: "The stock is counted in {stock_unit}, but the product is sold "
        "in {sales_unit}.",
        ReasonCode.NO_CONTENT_DATA: "The size of this product is not in the data.",
        ReasonCode.PARTIAL_AVAILABILITY: "Only {available_qty} of {needed_qty} in stock.",
        ReasonCode.STOCK_UNCONFIRMED: "Valio Aimo does not confirm the stock of this product.",
        ReasonCode.DELIVERY_AFTER_DEADLINE: "The first delivery is {available_date}, after "
        "{deliver_by}.",
    }
)


def reason_sentence(code: ReasonCode, **values: object) -> str:
    return REASON_TEXT[code].format(**values)


def day_text(day: date) -> str:
    """Mon 16 Nov: the style of the order pages."""
    return f"{day:%a} {day.day} {day:%b}"
