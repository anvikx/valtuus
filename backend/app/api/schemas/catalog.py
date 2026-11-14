from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.api.schemas.common import Allergens, PositiveQuantity, Quantity, RequestModel
from app.domain.catalog import SearchQuery
from app.domain.catalog_search import ATTRIBUTE_DESCRIPTION, QUERY_RULE
from app.domain.enums import Decision, ReasonCode, SearchMatch, SearchStatus, Unit


class SearchRequest(RequestModel):
    query: str = Field(
        description=f"{QUERY_RULE}. Accents are folded; substrings match.",
        examples=["milk"],
    )
    required_attributes: list[str] = Field(
        default_factory=list,
        description="Codes every product must have. " + ATTRIBUTE_DESCRIPTION,
        examples=[["FREE_FROM_LACTOSE"]],
    )
    quantity: PositiveQuantity | None = Field(
        default=None,
        description="How much the buyer needs, in `unit`.",
        examples=[1000],
    )
    unit: Unit | None = Field(default=None, description="Unit of `quantity`.", examples=["L"])
    deliver_by: date | None = Field(
        default=None,
        description="Latest delivery date the buyer accepts.",
        examples=["2026-11-16"],
    )
    preferred_brands: list[str] = Field(
        default_factory=list,
        description="Brands the buyer prefers. Not a filter.",
    )

    category: str | None = Field(default=None, description="Keep only this category code.")

    def to_domain(self) -> SearchQuery:
        return SearchQuery(
            query=self.query,
            required_attributes=tuple(self.required_attributes),
            quantity=self.quantity,
            unit=self.unit,
            deliver_by=self.deliver_by,
            preferred_brands=tuple(self.preferred_brands),
            category=self.category,
        )


class InterpretedRequest(BaseModel):
    query: str = Field(description="Product words as the gateway read them.")
    required_attributes: list[str] = Field(
        description="Attribute codes after the mandate's own required attributes were added.",
    )
    quantity: Quantity | None = Field(description="Requested quantity, in `unit`.")
    unit: Unit | None = Field(description="Unit of `quantity`.")
    deliver_by: date | None = Field(description="Latest delivery date.")
    preferred_brands: list[str] = Field(description="Brands the buyer prefers.")


class ContentPerSalesUnit(BaseModel):
    value: Quantity = Field(description="How much one sales unit holds.")
    unit: Unit | None = Field(description="Unit of `value`, when known.")


class SearchCandidate(BaseModel):
    product_id: str = Field(description="Valio Aimo product code. Send it to get_offers.")
    gtin: str | None = Field(description="GTIN of the unit that is ordered.")
    name: str = Field(description="Product name, in English when the data has it.")
    brand: str | None = Field(description="Brand.")
    sales_unit: str = Field(description="Technical code of the unit that is ordered.")
    content_per_sales_unit: ContentPerSalesUnit | None = Field(
        description="How much one sales unit holds.",
    )
    sales_units_needed: int | None = Field(
        description="Sales units that cover the requested quantity. null without a quantity.",
    )
    quantity_delivered: Quantity | None = Field(
        description="Quantity those sales units deliver, in the requested unit.",
    )
    quantity_over_request: Quantity | None = Field(
        description="How much the pack sizes give over the requested quantity.",
    )
    attributes: list[str] = Field(description="Attribute codes of the product.")
    allergens: Allergens = Field(description="Allergen data of the product.")
    country_of_origin: str | None = Field(description="2 letter country code.")
    labels: list[str] = Field(description="Package label codes.")
    is_substitute_for: str | None = Field(
        description="Product code this product can replace. null when it is not a substitute.",
    )

    match: SearchMatch = Field(
        default=SearchMatch.WHOLE_WORD,
        description="Whether all query words match whole words.",
    )


class ExcludedProduct(BaseModel):
    product_id: str = Field(description="Valio Aimo product code.")
    reason_code: ReasonCode = Field(description="Why the product was left out.")


class OptionRequest(BaseModel):
    query: str = Field(description="Product words to search with.")
    required_attributes: list[str] = Field(description="Attribute codes to search with.")
    quantity: Quantity | None = Field(description="Quantity, in `unit`.")
    unit: Unit | None = Field(description="Unit of `quantity`.")
    deliver_by: date | None = Field(description="Latest delivery date.")


class OptionEstimate(BaseModel):
    """Advice for a repeat option. The cart policy still decides."""

    unit_price: Decimal = Field(description="Price per sales unit, EUR ex VAT.")
    total_ex_vat: Decimal = Field(description="Estimated total, EUR ex VAT.")
    expected_decision: Decision = Field(description="The decision a cart would likely get.")
    expected_reason_codes: list[ReasonCode] = Field(description="Reasons for that decision.")
    expected_reason_sentences: list[str] = Field(
        description="One sentence per reason code, in the same order.",
    )
    max_auto_qty: int = Field(
        description="Largest quantity the agent may order without the main user.",
    )


class SearchOption(BaseModel):
    label: str = Field(description="Short text to show the buyer as a choice.")
    request: OptionRequest = Field(description="The search to send when the buyer picks it.")
    estimate: OptionEstimate | None = Field(description="Price and decision estimate, if known.")


class SearchResponse(BaseModel):
    hint_category: str | None = Field(
        default=None, description="Category of all returned candidates."
    )
    status: SearchStatus = Field(
        description="OK: candidates found. NEEDS_CLARIFICATION: ask the buyer first. "
        "NO_MATCH: no product matches.",
    )
    truncated: bool = Field(
        description="true when more products matched than the list holds. Narrow the search.",
    )
    interpreted_request: InterpretedRequest = Field(
        description="The request as the gateway read it."
    )
    missing: list[str] = Field(
        description="Request fields that the offers need and the request does not have.",
    )
    options: list[SearchOption] = Field(description="Choices to show the buyer.")
    candidates: list[SearchCandidate] = Field(
        description="Matching products. No price and no stock: get them from get_offers.",
    )
    excluded: list[ExcludedProduct] = Field(
        description="Products that matched but that the buyer's rules leave out.",
    )
    request_id: str = Field(description="Send it with get_offers for the same request.")
