from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.api.schemas.common import RequestModel
from app.domain.enums import Decision
from app.services.mandate_service import MandateChanges


class RankingWeights(BaseModel):
    """Weights, not money, so they stay numbers."""

    price: float
    reliability: float
    co2: float


class Mandate(BaseModel):
    buyer_id: str
    version: int
    max_auto_order_value: Decimal
    max_auto_value_per_delivery_date: Decimal
    max_line_value: Decimal | None
    required_attributes: list[str]
    forbidden_allergens: list[str]
    allergen_unknown_policy: Decision
    preferred_brands: list[str]
    ranking_weights: RankingWeights
    summary: list[str]


class MandateResponse(BaseModel):
    """`now` is the gateway clock. The agent resolves "Monday" from it, not from its own clock."""

    mandate: Mandate
    now: datetime
    timezone: str


class MandateUpdateRequest(RequestModel):
    """Only the fields to change. A missing field keeps its value."""

    max_auto_order_value: Decimal | None = Field(default=None, ge=0)
    max_auto_value_per_delivery_date: Decimal | None = Field(default=None, ge=0)
    preferred_brands: list[str] | None = None
    forbidden_allergens: list[str] | None = None
    allergen_unknown_policy: Decision | None = None

    def to_domain(self) -> MandateChanges:
        def as_tuple(values: list[str] | None) -> tuple[str, ...] | None:
            return None if values is None else tuple(values)

        return MandateChanges(
            max_auto_order_value=self.max_auto_order_value,
            max_auto_value_per_delivery_date=self.max_auto_value_per_delivery_date,
            preferred_brands=as_tuple(self.preferred_brands),
            forbidden_allergens=as_tuple(self.forbidden_allergens),
            allergen_unknown_policy=self.allergen_unknown_policy,
        )
