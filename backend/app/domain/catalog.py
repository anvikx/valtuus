from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.domain.enums import AllergenStatus, AllergenType, Decision, ReasonCode, SearchStatus, Unit


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


@dataclass(frozen=True)
class SearchCandidate:
    product_id: str
    gtin: str
    name: str
    brand: str
    sales_unit: str
    content_per_sales_unit: ContentPerSalesUnit
    sales_units_needed: int | None
    quantity_delivered: Decimal | None
    quantity_over_request: Decimal | None
    attributes: tuple[str, ...]
    allergens: Allergens
    country_of_origin: str | None
    labels: tuple[str, ...]
    is_substitute_for: str | None


@dataclass(frozen=True)
class ExcludedProduct:
    product_id: str
    reason_code: ReasonCode


@dataclass(frozen=True)
class OptionEstimate:
    unit_price: Decimal
    total_ex_vat: Decimal
    expected_decision: Decision
    expected_reason_codes: tuple[ReasonCode, ...]
    expected_reason_sentences: tuple[str, ...]
    max_auto_qty: int


@dataclass(frozen=True)
class SearchOption:
    label: str
    request: SearchQuery
    estimate: OptionEstimate | None


@dataclass(frozen=True)
class SearchResult:
    status: SearchStatus
    truncated: bool
    interpreted_request: SearchQuery
    missing: tuple[str, ...]
    options: tuple[SearchOption, ...]
    candidates: tuple[SearchCandidate, ...]
    excluded: tuple[ExcludedProduct, ...]
    request_id: str
