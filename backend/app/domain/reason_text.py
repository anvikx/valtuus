"""One sentence per reason code. The page, the agent's reply and the audit use the same text."""

from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from app.domain.constants import CURRENCY, GATEWAY_TIMEZONE
from app.domain.enums import ReasonCode
from app.domain.money import round_money

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
        ReasonCode.CUTOFF_PASSED: "The order deadline {deadline} has passed. Get new offers.",
        ReasonCode.PRICE_NOT_VALID_FOR_DATE: "The price ends {price_valid_to}, before the "
        "delivery {delivery_date}.",
        ReasonCode.PRICE_OR_STOCK_CHANGED: "The price or the stock changed after the offer. "
        "Get new offers.",
        ReasonCode.OVER_DAILY_AUTO_LIMIT: "Automatic orders for {delivery_date} would be "
        "{day_total}, over the {limit} daily limit.",
        ReasonCode.DUPLICATE_ORDER: "Possible duplicate: order {order_id} has the same product, "
        "quantity and delivery day.",
        ReasonCode.PREVIOUSLY_REJECTED: "A person rejected this same order at {rejected_at}: "
        '"{reject_reason}".',
        ReasonCode.AUTO_ORDERS_OFF: "Automatic orders are off.",
        ReasonCode.OVER_AUTO_LIMIT: "{total} is over the {limit} limit.",
        ReasonCode.OVER_LINE_LIMIT: "This line is {line_total}, over the {limit} line limit.",
        ReasonCode.QUANTITY_OVER_REQUEST: "The cart has {cart_qty}, more than the "
        "{requested_qty} requested.",
        ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE: "The substitute {substitute} is outside the "
        "main user's preferences.",
        ReasonCode.SUBSTITUTE_FOR_REQUESTED: "{substitute} replaces the requested {requested}.",
        ReasonCode.ALLERGEN_UNKNOWN: "The allergens of this product are not known.",
        ReasonCode.FORBIDDEN_ALLERGEN: "This product contains an allergen the main user forbids.",
        ReasonCode.MISSING_ATTRIBUTE: "This product is not {attribute}, which the main user "
        "requires.",
        ReasonCode.SALES_BLOCKED: "Valio Aimo has blocked the sale of this product.",
        ReasonCode.OFFER_EXPIRED: "The offer has expired. Get new offers.",
        ReasonCode.NEEDS_CLARIFICATION: "The request is not clear. Ask the buyer: {question}",
        ReasonCode.KEY_REVOKED: "The main user revoked this agent key.",
        ReasonCode.SCOPE_MISSING: "This agent key does not have the {scope} scope.",
        ReasonCode.HUMAN_SESSION_REQUIRED: "{agent_name} tried {method} {path}, which only the "
        "main user can do.",
    }
)


def reason_sentence(code: ReasonCode, **values: object) -> str:
    return REASON_TEXT[code].format(**values)


def day_text(day: date) -> str:
    """Mon 16 Nov: the style of the order pages."""
    return f"{day:%a} {day.day} {day:%b}"


def deadline_text(moment: datetime) -> str:
    """Sun 15 Nov 17:00 in gateway time, including after a UTC database read."""
    local = moment.astimezone(GATEWAY_TIMEZONE)
    return f"{day_text(local.date())} {local:%H:%M}"


def money_text(amount: Decimal) -> str:
    """1,010.00 EUR: grouped, so the main user reads a large total at a glance."""
    # Rounded here, because the format spec alone rounds half even.
    return f"{round_money(amount):,.2f} {CURRENCY}"
