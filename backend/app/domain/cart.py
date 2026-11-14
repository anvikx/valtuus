from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.domain.catalog import SearchQuery
from app.domain.enums import CartState, Decision, ReasonCode
from app.domain.offer import SubstituteFor


@dataclass(frozen=True)
class CartLineInput:
    """What the agent may send for a line. Price, stock and date come from the stored offer."""

    offer_id: str
    product_id: str
    qty: int


@dataclass(frozen=True)
class CartDraft:
    lines: tuple[CartLineInput, ...]
    request_text: str
    clarifications: tuple[str, ...]


@dataclass(frozen=True)
class PricedLine:
    """A draft line with its price and dates from the stored offer, before the policy runs."""

    offer_id: str
    product_id: str
    name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date
    closing_time: datetime
    substitute_for: SubstituteFor | None


@dataclass(frozen=True)
class CartLine:
    offer_id: str
    product_id: str
    name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date
    closing_time: datetime
    decision: Decision
    substitute_for: SubstituteFor | None
    reason_codes: tuple[ReasonCode, ...]
    reason_sentences: tuple[str, ...]


@dataclass(frozen=True)
class Cart:
    """Lines and prices never change after create_cart. Only the state fields move."""

    cart_id: str
    buyer_id: str
    agent_name: str
    state: CartState
    decision: Decision
    reason_codes: tuple[ReasonCode, ...]
    reason_sentences: tuple[str, ...]
    current_decision: Decision
    current_reason_codes: tuple[ReasonCode, ...]
    request_text: str
    clarifications: tuple[str, ...]
    interpreted_request: SearchQuery | None
    lines: tuple[CartLine, ...]
    total_ex_vat: Decimal
    currency: str
    mandate_version: int
    valid_until: datetime
    approve_before: datetime
    duplicate_of_order_id: str | None
    delivery_day_total_ex_vat: Decimal
    order_id: str | None
    previous_reject_reason: str | None
    decided_by: str | None
    decided_at: datetime | None
    reject_reason: str | None
