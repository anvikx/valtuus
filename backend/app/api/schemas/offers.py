from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.common import Allergens, PositiveQuantity, Quantity, Reasons, RequestModel
from app.domain.audit import REQUEST_ID_PATTERN
from app.domain.enums import OfferTier, ReasonCode, StockModel, SubstituteBasis, Unit
from app.domain.offer import OfferQuery


class OfferRequest(RequestModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "product_ids": ["464306"],
                    "quantity": 1000,
                    "unit": "L",
                    "deliver_by": "2026-11-16",
                },
            ],
        },
    )

    product_ids: list[str] = Field(
        min_length=1,
        description="Product codes from search_products. Send all candidates.",
    )
    quantity: PositiveQuantity | None = Field(default=None, description="Quantity, in `unit`.")
    unit: Unit | None = Field(default=None, description="Unit of `quantity`.")
    deliver_by: date | None = Field(default=None, description="Latest delivery date.")
    preferred_brands: list[str] = Field(
        default_factory=list,
        description="Brands to prioritize. The mandate's preferred brands take precedence.",
    )
    include_substitutes: bool = Field(
        default=False,
        description="true: also offer substitutes for products that cannot be delivered.",
    )
    request_id: str | None = Field(
        default=None,
        pattern=REQUEST_ID_PATTERN,
        description="request_id from search_products, so the audit trail links the search "
        "to the cart. null: the gateway starts a new request.",
    )

    def to_domain(self) -> OfferQuery:
        return OfferQuery(
            product_ids=tuple(self.product_ids),
            quantity=self.quantity,
            unit=self.unit,
            deliver_by=self.deliver_by,
            preferred_brands=tuple(self.preferred_brands),
            include_substitutes=self.include_substitutes,
            request_id=self.request_id,
        )


class RequestedItem(BaseModel):
    quantity: Quantity | None = Field(description="Requested quantity, in `unit`.")
    unit: Unit | None = Field(description="Unit of `quantity`.")
    deliver_by: date | None = Field(description="Latest delivery date.")


class ComparisonPrice(BaseModel):
    value: Decimal = Field(description="Price per `per`, EUR ex VAT.")
    per: Unit = Field(description="Unit of the comparison, such as L or KG.")


class SubstituteFor(BaseModel):
    product_id: str = Field(description="Product that is replaced.")
    name: str = Field(description="Name of that product.")
    basis: SubstituteBasis = Field(
        description="VALIO_PAIR: Valio Aimo names this substitute. SAME_CATEGORY: same category.",
    )
    reason_code: ReasonCode = Field(description="Why the original product is not offered.")
    reason_sentence: str = Field(description="The reason in one sentence.")
    price_difference_per_unit: Decimal = Field(
        description="Substitute price minus original price per sales unit, EUR ex VAT.",
    )


class OfferLine(Reasons):
    rank: int = Field(
        description="1 is best: on-time delivery, preferred brand, stock, then price."
    )
    tier: OfferTier | None = Field(description="Ranking tier of the line.")
    product_id: str = Field(description="Valio Aimo product code.")
    gtin: str | None = Field(description="GTIN of the unit that is ordered. null: no data.")
    name: str = Field(description="Product name.")
    brand: str | None = Field(description="Brand. null: no data.")
    country_of_origin: str | None = Field(description="2 letter country code.")
    labels: list[str] = Field(description="Package label codes.")
    allergens: Allergens = Field(description="Allergen data of the product.")
    delivery_reliability: Decimal | None = Field(
        description="Delivery reliability of the product. null: no data.",
    )
    co2_kg_per_kg: Decimal | None = Field(description="kg CO2 per kg of product. null: no data.")
    sales_units_needed: int = Field(description="Sales units that cover the requested quantity.")
    unit_price: Decimal = Field(description="Price per sales unit, EUR ex VAT.")
    currency: str = Field(description="Always EUR.")
    vat_rate: Decimal | None = Field(
        description="VAT rate. Prices exclude VAT. null: Valio Aimo sent no tax."
    )
    comparison_price: ComparisonPrice = Field(description="Price per L or per KG, to compare.")
    price_valid_from: date = Field(description="First day of the price.")
    price_valid_to: date = Field(description="Last day of the price.")
    stock_model: StockModel | None = Field(
        description="STOCK: a count, except 999999 or more is unknown. TERMINAL: no count, so "
        "available_qty is null. null: not given, ranked as stock not confirmed.",
    )
    available_qty: int | None = Field(
        description="Stock at source_time, not a reservation. null: amount not known.",
    )
    available_date: date = Field(description="First delivery date.")
    closing_time: datetime = Field(description="Order deadline for that date.")
    line_total: Decimal = Field(description="sales_units_needed x unit_price, EUR ex VAT.")
    max_auto_qty: int | None = Field(
        description="Largest quantity the agent may order without the main user. null: not "
        "computed, so the cart policy decides. Never read null as 0 or as no limit.",
    )
    substitute_for: SubstituteFor | None = Field(
        description="Product this line replaces. null when it is not a substitute.",
    )


class SplitLine(BaseModel):
    product_id: str = Field(description="Valio Aimo product code.")
    qty: int = Field(description="Sales units of this product.")
    reason_codes: list[ReasonCode] = Field(description="Why the split uses this product.")


class ProposedSplit(BaseModel):
    lines: list[SplitLine] = Field(description="Products that together cover the quantity.")
    unfilled_qty: int = Field(description="Quantity no product can deliver.")


class RejectedProduct(BaseModel):
    product_id: str = Field(description="Valio Aimo product code.")
    name: str = Field(description="Product name.")
    reason_code: ReasonCode = Field(description="Why the product has no offer line.")
    reason_sentence: str = Field(description="The reason in one sentence.")
    closing_time: datetime | None = Field(
        default=None,
        description="The passed order deadline, for CUTOFF_PASSED.",
    )


class OfferResponse(BaseModel):
    offer_id: str = Field(description="Offer id. Send it with each cart line.")
    issuer: str = Field(description="Who signs the offer.")
    issued_at: datetime = Field(description="Time the gateway made the offer.")
    source_time: datetime = Field(description="Time of the price and stock data at Valio Aimo.")
    valid_until: datetime = Field(
        description="Limits only how long the stock snapshot may be used. The price holds "
        "until price_valid_to.",
    )
    requested: RequestedItem = Field(description="The request the offer answers.")
    lines: list[OfferLine] = Field(description="Offer lines, best rank first.")
    proposed_split: ProposedSplit | None = Field(
        description="Several products for a quantity one product cannot cover. null: not needed.",
    )
    rejected: list[RejectedProduct] = Field(description="Products with no offer line, and why.")
    signature: str | None = Field(
        description="Compact JWS (EdDSA) over this body without signature. Check it with the "
        "key in /.well-known/jwks.json. null: the gateway has no signing key.",
    )
    request_id: str | None = Field(description="Id of the buyer request the offer belongs to.")
