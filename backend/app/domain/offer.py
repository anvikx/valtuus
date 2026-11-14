from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

from app.domain.catalog import Allergens
from app.domain.enums import OfferTier, ReasonCode, StockModel, SubstituteBasis, Unit


@dataclass(frozen=True)
class ComparisonPrice:
    value: Decimal
    per: Unit


@dataclass(frozen=True)
class Price:
    """One answer line of the price API, parsed. Absent from the result = no price."""

    product_id: str
    unit_price: Decimal
    vat_rate: Decimal
    comparison_price: ComparisonPrice | None
    valid_from: date
    valid_to: date


@dataclass(frozen=True)
class Availability:
    """One answer line of the availability API, parsed. The markers stay raw numbers here."""

    product_id: str
    stock_model: StockModel | None
    amount: int | None
    available_date: date | None
    closing_time: datetime | None
    is_sales_blocked: bool


@dataclass(frozen=True)
class AvailabilitySnapshot:
    source_time: datetime
    items: Mapping[str, Availability]

    def __post_init__(self) -> None:
        # frozen stops a new map, not a change inside the old one. Copy, then wrap read only.
        object.__setattr__(self, "items", MappingProxyType(dict(self.items)))


@dataclass(frozen=True)
class OfferQuery:
    product_ids: tuple[str, ...]
    quantity: Decimal | None
    unit: Unit | None
    deliver_by: date | None
    preferred_brands: tuple[str, ...]
    include_substitutes: bool


@dataclass(frozen=True)
class RequestedItem:
    quantity: Decimal | None
    unit: Unit | None
    deliver_by: date | None


@dataclass(frozen=True)
class SubstituteFor:
    product_id: str
    name: str
    basis: SubstituteBasis
    reason_code: ReasonCode
    reason_sentence: str
    price_difference_per_unit: Decimal


@dataclass(frozen=True)
class OfferLine:
    rank: int
    tier: OfferTier | None
    product_id: str
    gtin: str
    name: str
    brand: str
    country_of_origin: str | None
    labels: tuple[str, ...]
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
    available_qty: int | None
    available_date: date
    closing_time: datetime
    line_total: Decimal
    max_auto_qty: int
    substitute_for: SubstituteFor | None
    reason_codes: tuple[ReasonCode, ...]
    reason_sentences: tuple[str, ...]


@dataclass(frozen=True)
class SplitLine:
    product_id: str
    qty: int
    reason_codes: tuple[ReasonCode, ...]


@dataclass(frozen=True)
class ProposedSplit:
    lines: tuple[SplitLine, ...]
    unfilled_qty: int


@dataclass(frozen=True)
class RejectedProduct:
    product_id: str
    name: str
    reason_code: ReasonCode
    reason_sentence: str
    closing_time: datetime | None


@dataclass(frozen=True)
class Offer:
    """The stored offer. A cart reads its prices from here, never from the agent."""

    offer_id: str
    buyer_id: str
    issuer: str
    issued_at: datetime
    source_time: datetime
    valid_until: datetime
    requested: RequestedItem
    lines: tuple[OfferLine, ...]
    proposed_split: ProposedSplit | None
    rejected: tuple[RejectedProduct, ...]
    signature: str | None
