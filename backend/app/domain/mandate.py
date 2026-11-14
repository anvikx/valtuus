from dataclasses import dataclass
from decimal import Decimal

from app.domain.enums import Decision, EnvelopeMode

_DEFAULT_QUANTITY_FACTOR = Decimal("2")
_DEFAULT_PRICE_INCREASE_PCT = Decimal("10")

# Every GS1 allergen type code the catalog declares (checked 15 Nov 2026, 17,546 products).
# The policy compares codes exactly, so a code outside this list would match no product.
VALID_ALLERGENS = (
    "ABD",
    "AC",
    "ADQ",
    "AE",
    "AF",
    "AM",
    "AN",
    "AP",
    "AS",
    "AU",
    "AW",
    "AY",
    "BC",
    "BF",
    "BM",
    "BP",
    "CM",
    "GB",
    "GK",
    "GO",
    "GS",
    "ML",
    "NC",
    "NE",
    "NK",
    "NL",
    "NM",
    "NP",
    "NR",
    "NW",
    "PN",
    "PO",
    "SA",
    "SC",
    "SH",
    "SM",
    "SO",
    "SP",
    "SR",
    "ST",
    "SW",
    "UM",
    "UN",
    "UW",
    "X99",
)
ALLERGEN_DESCRIPTION = "Valid allergen codes: " + ", ".join(VALID_ALLERGENS) + "."


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
    # Off unless the main user turns it on. A version stored before this field loads as off.
    can_auto_order: bool = False
    envelope_mode: EnvelopeMode = EnvelopeMode.HUMAN
    quantity_factor: Decimal = _DEFAULT_QUANTITY_FACTOR
    price_increase_pct: Decimal = _DEFAULT_PRICE_INCREASE_PCT
