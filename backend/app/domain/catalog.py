from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.domain.enums import (
    AllergenStatus,
    AllergenType,
    ReasonCode,
    SearchHintCode,
    SearchMatch,
    Unit,
)


@dataclass(frozen=True)
class Allergens:
    """UNKNOWN when the data lists nothing: an empty list does not mean free from."""

    status: AllergenStatus
    free_from: tuple[str, ...]
    declarations: dict[AllergenType, tuple[str, ...]] = field(default_factory=dict)

    @property
    def contains(self) -> tuple[str, ...]:
        return tuple(sorted({code for codes in self.declarations.values() for code in codes}))


@dataclass(frozen=True)
class ContentPerSalesUnit:
    value: Decimal
    unit: Unit | None
    source: str | None = None


@dataclass(frozen=True)
class Product:
    """One product of the challenge file, with the fields the gateway uses."""

    product_id: str
    gtin: str | None
    name: str
    names: dict[str, str]
    brand: str | None
    category: str
    sales_unit: str
    content_per_sales_unit: ContentPerSalesUnit | None
    attributes: tuple[str, ...]
    allergens: Allergens
    country_of_origin: str | None
    labels: tuple[str, ...]
    substitute_ids: tuple[str, ...]
    delivery_reliability: Decimal | None
    co2_kg_per_kg: Decimal | None
    lot_size: Decimal | None = None
    is_variable_weight: bool = False
    deposits: tuple[dict[str, Any], ...] = ()
    ingredients: tuple[dict[str, Any], ...] = ()
    ingredient_texts: tuple[dict[str, Any], ...] = ()
    nutrition: tuple[dict[str, Any], ...] = ()
    nutritional_claims: tuple[str, ...] = ()
    packaging_labels: tuple[str, ...] = ()
    key_ingredients: str | None = None
    fat: Decimal | None = None
    sugar: Decimal | None = None
    protein: Decimal | None = None


@dataclass(frozen=True)
class SearchQuery:
    query: str
    required_attributes: tuple[str, ...]
    quantity: Decimal | None
    unit: Unit | None
    deliver_by: date | None
    preferred_brands: tuple[str, ...]
    category: str | None = None


@dataclass(frozen=True)
class SearchCandidate:
    product_id: str
    gtin: str | None
    name: str
    brand: str | None
    sales_unit: str
    content_per_sales_unit: ContentPerSalesUnit | None
    sales_units_needed: int | None
    quantity_delivered: Decimal | None
    quantity_over_request: Decimal | None
    attributes: tuple[str, ...]
    allergens: Allergens
    country_of_origin: str | None
    labels: tuple[str, ...]
    is_substitute_for: str | None
    match: SearchMatch = SearchMatch.WHOLE_WORD


@dataclass(frozen=True)
class ExcludedProduct:
    product_id: str
    reason_code: ReasonCode


@dataclass(frozen=True)
class CategorySummary:
    category: str
    hits: int
    examples: tuple[str, ...]
    in_list: bool


@dataclass(frozen=True)
class SearchHint:
    code: SearchHintCode
    sentence: str


@dataclass(frozen=True)
class SearchResult:
    understood: SearchQuery
    candidates: tuple[SearchCandidate, ...]
    total_hits: int
    categories: tuple[CategorySummary, ...]
    hint: SearchHint
    hint_category: str | None
    excluded: tuple[ExcludedProduct, ...]
    missing_fields: tuple[str, ...]
    request_id: str
