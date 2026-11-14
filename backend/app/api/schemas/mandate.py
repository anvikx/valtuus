from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.domain.enums import Decision


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
