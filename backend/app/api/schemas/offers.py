from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas.common import Allergens, PositiveQuantity, Quantity, Reasons, RequestModel
from app.domain.constants import MAX_OFFER_CANDIDATES
from app.domain.enums import OfferTier, ReasonCode, StockModel, Unit


class OfferRequest(RequestModel):
    product_ids: list[str] = Field(min_length=1, max_length=MAX_OFFER_CANDIDATES)
    quantity: PositiveQuantity | None = None
    unit: Unit | None = None
    deliver_by: date | None = None
    preferred_brands: list[str] = Field(default_factory=list)
    include_substitutes: bool = False


class RequestedItem(BaseModel):
    quantity: Quantity | None
    unit: Unit | None
    deliver_by: date | None


class ComparisonPrice(BaseModel):
    value: Decimal
    per: Unit


class SubstituteFor(BaseModel):
    product_id: str
    name: str
    basis: Literal["VALIO_PAIR", "SAME_CATEGORY"]
    reason_code: ReasonCode
    reason_sentence: str
    price_difference_per_unit: Decimal


class OfferLine(Reasons):
    rank: int
    tier: OfferTier | None
    product_id: str
    gtin: str
    name: str
    brand: str
    country_of_origin: str | None
    labels: list[str]
    allergens: Allergens
    delivery_reliability: Decimal | None
    co2_kg_per_kg: Decimal | None
    sales_units_needed: int
    unit_price: Decimal
    currency: str
    vat_rate: Decimal
    comparison_price: ComparisonPrice
    price_valid_from: date
    price_valid_to: date
    stock_model: StockModel
    available_qty: int | None = Field(
        description="Stock at source_time, not a reservation. null: not known, or no limit.",
    )
    available_date: date
    closing_time: datetime
    line_total: Decimal
    max_auto_qty: int
    substitute_for: SubstituteFor | None


class SplitLine(BaseModel):
    product_id: str
    qty: int
    reason_codes: list[ReasonCode]


class ProposedSplit(BaseModel):
    lines: list[SplitLine]
    unfilled_qty: int


class RejectedProduct(BaseModel):
    product_id: str
    name: str
    reason_code: ReasonCode
    reason_sentence: str
    closing_time: datetime | None = None


class OfferResponse(BaseModel):
    offer_id: str
    issuer: str
    issued_at: datetime
    source_time: datetime
    valid_until: datetime = Field(
        description="Limits only how long the stock snapshot may be used. The price holds "
        "until price_valid_to.",
    )
    requested: RequestedItem
    lines: list[OfferLine]
    proposed_split: ProposedSplit | None
    rejected: list[RejectedProduct]
    signature: str | None
