from datetime import date, datetime
from decimal import Decimal

from pydantic import ConfigDict, Field

from app.api.schemas.catalog import InterpretedRequest
from app.api.schemas.common import PositiveSalesUnits, Reasons, RequestModel
from app.api.schemas.offers import SubstituteFor
from app.domain.cart import CartDraft, CartLineInput
from app.domain.enums import CartState, Decision, ReasonCode


class CartLineRequest(RequestModel):
    offer_id: str = Field(description="Offer that holds the line.", examples=["o_1"])
    product_id: str = Field(description="Product code of an offer line.", examples=["464306"])
    qty: PositiveSalesUnits = Field(description="Sales units.", examples=[1000])


class CartRequest(RequestModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "lines": [{"offer_id": "o_1", "product_id": "464306", "qty": 1000}],
                    "request_text": "1000 l lactose free milk for Monday",
                    "clarifications": ["Yes, order it."],
                },
            ],
        },
    )

    lines: list[CartLineRequest] = Field(min_length=1, description="Offer lines to buy.")
    request_text: str = Field(description="The buyer's own words, for the audit record.")
    clarifications: list[str] = Field(
        default_factory=list,
        description="The buyer's answers to the agent's questions, in the buyer's words.",
    )

    def to_domain(self) -> CartDraft:
        return CartDraft(
            lines=tuple(
                CartLineInput(offer_id=line.offer_id, product_id=line.product_id, qty=line.qty)
                for line in self.lines
            ),
            request_text=self.request_text,
            clarifications=tuple(self.clarifications),
        )


class RejectRequest(RequestModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"reason": "Too expensive."}]})

    reason: str = Field(min_length=1, description="Why the main user rejects the cart.")


class CartLine(Reasons):
    offer_id: str = Field(description="Offer that holds the line.")
    product_id: str = Field(description="Valio Aimo product code.")
    name: str = Field(description="Product name.")
    qty: int = Field(description="Sales units.")
    unit_price: Decimal = Field(description="Price per sales unit, EUR ex VAT.")
    line_total: Decimal = Field(description="qty x unit_price, EUR ex VAT.")
    delivery_date: date = Field(description="Delivery date.")
    closing_time: datetime = Field(description="Order deadline for the delivery date.")
    decision: Decision = Field(description="Decision for this line.")
    substitute_for: SubstituteFor | None = Field(
        description="Product this line replaces. null when it is not a substitute.",
    )


class CartResponse(Reasons):
    cart_id: str = Field(description="Cart id.")
    state: CartState = Field(
        description="AUTO: check out now. PENDING_APPROVAL: the main user decides. "
        "ORDERED, REJECTED, EXPIRED, DENIED: closed.",
    )
    decision: Decision = Field(
        description="Decision when the cart was made: the strictest of DENY, HUMAN, AUTO.",
    )
    current_decision: Decision = Field(
        description="Decision by the current mandate. Checkout and approval use this one.",
    )
    current_reason_codes: list[ReasonCode] = Field(
        description="Reasons for current_decision.",
    )
    request_text: str = Field(description="The buyer's words, as the agent sent them.")
    clarifications: list[str] = Field(description="The buyer's answers, as the agent sent them.")
    interpreted_request: InterpretedRequest | None = Field(
        description="The search request behind the cart, if known.",
    )
    lines: list[CartLine] = Field(description="Cart lines. They never change.")
    total_ex_vat: Decimal = Field(description="Cart total, EUR ex VAT.")
    currency: str = Field(description="Always EUR.")
    mandate_version: int = Field(description="Mandate version of `decision`.")
    valid_until: datetime = Field(
        description="Stock snapshot limit. After it, checkout fetches fresh price and stock.",
    )
    approve_before: datetime = Field(
        description="Earliest order deadline of the lines. After it, the cart is EXPIRED.",
    )
    duplicate_of_order_id: str | None = Field(
        description="Order this cart repeats (DUPLICATE_ORDER). null otherwise.",
    )
    delivery_day_total_ex_vat: Decimal = Field(
        description="Automatic orders for the delivery date plus this cart, EUR ex VAT.",
    )
    order_id: str | None = Field(description="Placed order. null until ORDERED.")
    previous_reject_reason: str | None = Field(
        description="Reason the main user gave when they rejected the same cart before.",
    )
    decided_by: str | None = Field(description="Main user who approved or rejected.")
    decided_at: datetime | None = Field(description="Time of that decision.")
    reject_reason: str | None = Field(description="Why the main user rejected the cart.")
    approve_url: str | None = Field(
        description="Page where the main user approves or rejects. null unless PENDING_APPROVAL.",
    )
    next_step: str | None = Field(
        description="What the agent tells the buyer now. null unless PENDING_APPROVAL.",
    )
