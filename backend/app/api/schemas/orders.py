from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.api.schemas.offers import SubstituteFor
from app.domain.enums import Ledger, OrderStatus


class OrderLine(BaseModel):
    product_id: str = Field(description="Valio Aimo product code.")
    gtin: str | None = Field(description="GTIN of the unit that is ordered. null: no data.")
    name: str = Field(description="Product name.")
    qty: int = Field(description="Sales units.")
    unit_price: Decimal = Field(description="Price per sales unit, EUR ex VAT.")
    line_total: Decimal = Field(description="qty x unit_price, EUR ex VAT.")
    delivery_date: date = Field(description="Delivery date.")
    substitute_for: SubstituteFor | None = Field(
        description="Product this line replaces. null when it is not a substitute.",
    )


class OrderConfirmation(BaseModel):
    order_id: str = Field(description="Order id.")
    cart_id: str = Field(description="Cart the order came from.")
    revision: int = Field(description="Cart revision that was ordered.")
    buyer_id: str = Field(description="Buyer id.")
    status: OrderStatus = Field(description="CONFIRMED.")
    ledger: Ledger = Field(
        description="The order is kept in the prototype's ledger. It is not sent to a Valio "
        "Aimo production system.",
    )
    lines: list[OrderLine] = Field(description="Order lines.")
    total_ex_vat: Decimal = Field(description="Order total, EUR ex VAT.")
    currency: str = Field(description="Always EUR.")
    placed_at: datetime = Field(description="Time of the order.")
    placed_by: str = Field(description="Agent or main user that placed it.")
    approved_by: str | None = Field(description="null when the agent ordered within its mandate.")
    offer_ids: list[str] = Field(description="Offers the order used.")
    mandate_version: int = Field(description="Mandate version that allowed the order.")
    issuer: str = Field(description="Who signs the confirmation.")
    signature: str | None = Field(
        description="Compact JWS (EdDSA) over this body without signature. Check it with the "
        "key in /.well-known/jwks.json. null: the gateway has no signing key."
    )
