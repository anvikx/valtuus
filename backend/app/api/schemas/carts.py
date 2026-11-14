from datetime import date, datetime
from decimal import Decimal

from pydantic import Field

from app.api.schemas.catalog import InterpretedRequest
from app.api.schemas.common import Reasons, RequestModel
from app.api.schemas.offers import SubstituteFor
from app.domain.enums import CartState, Decision, ReasonCode


class CartLineRequest(RequestModel):
    offer_id: str
    product_id: str
    qty: int = Field(gt=0, description="Sales units.")


class CartRequest(RequestModel):
    lines: list[CartLineRequest] = Field(min_length=1)
    request_text: str = Field(description="The buyer's own words, for the audit record.")
    clarifications: list[str] = Field(default_factory=list)


class RejectRequest(RequestModel):
    reason: str = Field(min_length=1)


class CartLine(Reasons):
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


class CartResponse(Reasons):
    cart_id: str
    state: CartState
    decision: Decision
    current_decision: Decision
    current_reason_codes: list[ReasonCode]
    request_text: str
    clarifications: list[str]
    interpreted_request: InterpretedRequest | None
    lines: list[CartLine]
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
    approve_url: str
