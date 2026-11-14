from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.api.schemas.offers import SubstituteFor
from app.domain.enums import Ledger, OrderStatus


class OrderLine(BaseModel):
    product_id: str
    gtin: str
    name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date
    substitute_for: SubstituteFor | None


class OrderConfirmation(BaseModel):
    order_id: str
    cart_id: str
    buyer_id: str
    status: OrderStatus
    ledger: Ledger = Field(
        description="The order is kept in the prototype's ledger. It is not sent to a Valio "
        "Aimo production system.",
    )
    lines: list[OrderLine]
    total_ex_vat: Decimal
    currency: str
    placed_at: datetime
    placed_by: str
    approved_by: str | None = Field(description="null when the agent ordered within its mandate.")
    offer_ids: list[str]
    mandate_version: int
    issuer: str
    signature: str | None
