from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.domain.enums import Ledger, OrderStatus
from app.domain.offer import SubstituteFor


@dataclass(frozen=True)
class OrderLine:
    product_id: str
    gtin: str | None
    name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    delivery_date: date
    substitute_for: SubstituteFor | None


@dataclass(frozen=True)
class Order:
    order_id: str
    cart_id: str
    buyer_id: str
    lines: tuple[OrderLine, ...]
    total_ex_vat: Decimal
    currency: str
    placed_at: datetime
    placed_by: str
    approved_by: str | None
    offer_ids: tuple[str, ...]
    mandate_version: int
    issuer: str
    signature: str | None
    status: OrderStatus = OrderStatus.CONFIRMED
    ledger: Ledger = Ledger.PROTOTYPE
    # The cart revision this order was placed from.
    revision: int = 1
