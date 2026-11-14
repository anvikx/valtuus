from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.api.schemas.common import Allergens, PositiveQuantity, Quantity, RequestModel
from app.domain.enums import Decision, ReasonCode, SearchStatus, Unit


class SearchRequest(RequestModel):
    query: str
    required_attributes: list[str] = Field(default_factory=list)
    quantity: PositiveQuantity | None = None
    unit: Unit | None = None
    deliver_by: date | None = None
    preferred_brands: list[str] = Field(default_factory=list)


class InterpretedRequest(BaseModel):
    query: str
    required_attributes: list[str]
    quantity: Quantity | None
    unit: Unit | None
    deliver_by: date | None
    preferred_brands: list[str]


class ContentPerSalesUnit(BaseModel):
    value: Quantity
    unit: Unit


class SearchCandidate(BaseModel):
    product_id: str
    gtin: str
    name: str
    brand: str
    sales_unit: str
    content_per_sales_unit: ContentPerSalesUnit
    sales_units_needed: int | None
    quantity_delivered: Quantity | None
    quantity_over_request: Quantity | None
    attributes: list[str]
    allergens: Allergens
    country_of_origin: str | None
    labels: list[str]
    is_substitute_for: str | None


class ExcludedProduct(BaseModel):
    product_id: str
    reason_code: ReasonCode


class OptionRequest(BaseModel):
    query: str
    required_attributes: list[str]
    quantity: Quantity | None
    unit: Unit | None
    deliver_by: date | None


class OptionEstimate(BaseModel):
    """Advice for a repeat option. The cart policy still decides."""

    unit_price: Decimal
    total_ex_vat: Decimal
    expected_decision: Decision
    expected_reason_codes: list[ReasonCode]
    expected_reason_sentences: list[str]
    max_auto_qty: int


class SearchOption(BaseModel):
    label: str
    request: OptionRequest
    estimate: OptionEstimate | None


class SearchResponse(BaseModel):
    status: SearchStatus
    truncated: bool
    interpreted_request: InterpretedRequest
    missing: list[str]
    options: list[SearchOption]
    candidates: list[SearchCandidate]
    excluded: list[ExcludedProduct]
