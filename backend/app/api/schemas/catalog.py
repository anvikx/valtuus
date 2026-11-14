from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, WithJsonSchema

from app.api.schemas.common import Allergens, PositiveQuantity, Quantity, RequestModel
from app.domain.catalog import SearchQuery
from app.domain.catalog_search import ATTRIBUTE_DESCRIPTION, QUERY_RULE, VALID_ATTRIBUTES
from app.domain.enums import ReasonCode, SearchHintCode, SearchMatch, Unit

# The schema lists the codes, but validate_query rejects a wrong one. A pydantic enum would make
# the MCP SDK refuse the call first, with its own text and no error code or next_step.
AttributeCodeValue = Annotated[
    str,
    WithJsonSchema(
        {
            "type": "string",
            "enum": list(VALID_ATTRIBUTES),
        },
    ),
]


class SearchRequest(RequestModel):
    query: str = Field(
        description=f"{QUERY_RULE}. Accents are folded; substrings match.",
        examples=["milk"],
    )
    required_attributes: list[AttributeCodeValue] = Field(
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


class UnderstoodRequest(InterpretedRequest):
    category: str | None = Field(description="Requested category code, when given.")


class CategorySummary(BaseModel):
    category: str = Field(description="Product category code; names are not available.")
    hits: int = Field(description="All filtered hits in this category, before the safety guard.")
    examples: list[str] = Field(description="Up to two distinct example product names.")


class SearchHint(BaseModel):
    code: SearchHintCode = Field(description="One deterministic advice code for the next step.")
    sentence: str = Field(description="Fixed advice for the agent; never blocks another call.")


class SearchResponse(BaseModel):
    understood: UnderstoodRequest = Field(
        description="Normalized request and effective attributes."
    )
    candidates: list[SearchCandidate] = Field(
        description="Every hit in hint_category, subject to the safety guard. No price or stock.",
    )
    total_hits: int = Field(
        description="All filtered hits across categories, before the safety guard."
    )
    categories: list[CategorySummary] = Field(
        description="Top eight categories from all filtered hits."
    )
    hint: SearchHint = Field(description="Exactly one advisory hint, selected by fixed priority.")
    hint_category: str | None = Field(
        description="Requested or selected category; null when neither is available."
    )
    excluded: list[ExcludedProduct] = Field(
        description="Products removed by mandate allergen rules."
    )
    missing_fields: list[str] = Field(
        description="Missing quantity, unit or deliver_by for offers."
    )
    request_id: str = Field(description="Send it with get_offers for the same request.")
