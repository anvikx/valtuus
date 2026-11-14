from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import Decision


@dataclass(frozen=True)
class RankingWeights:
    price: float
    reliability: float
    co2: float


@dataclass(frozen=True)
class Mandate:
    """One version of a buyer's rules. A change makes a new version; old versions stay."""

    buyer_id: str
    version: int
    max_auto_order_value: Decimal
    max_auto_value_per_delivery_date: Decimal
    max_line_value: Decimal | None
    required_attributes: tuple[str, ...]
    forbidden_allergens: tuple[str, ...]
    allergen_unknown_policy: Decision
    preferred_brands: tuple[str, ...]
    ranking_weights: RankingWeights
