from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.api.schemas.catalog import AttributeCodeValue
from app.api.schemas.common import RequestModel
from app.domain.constants import MAX_MANDATE_LIMIT, MONEY_DECIMALS
from app.domain.enums import Decision
from app.domain.money import round_money
from app.services.mandate_service import MandateChanges


class RankingWeights(BaseModel):
    """Weights, not money, so they stay numbers."""

    price: float = Field(description="Weight of a low price.")
    reliability: float = Field(description="Weight of delivery reliability.")
    co2: float = Field(description="Weight of low CO2.")


class Mandate(BaseModel):
    buyer_id: str = Field(description="Buyer id.")
    version: int = Field(description="Goes up by 1 on each change.")
    max_auto_order_value: Decimal = Field(
        description="Largest cart the agent may order without the main user, EUR ex VAT. "
        "0: proposals only.",
    )
    max_auto_value_per_delivery_date: Decimal = Field(
        description="Largest total of automatic orders for one delivery date, EUR ex VAT.",
    )
    max_line_value: Decimal | None = Field(description="Largest line, EUR ex VAT. null: no limit.")
    required_attributes: list[str] = Field(description="Codes every product must have.")
    forbidden_allergens: list[str] = Field(
        description="Allergen codes the buyer never buys. May contain counts as contains.",
    )
    allergen_unknown_policy: Decision = Field(
        description="Decision for a product with UNKNOWN allergens.",
    )
    preferred_brands: list[str] = Field(description="Brands the buyer prefers.")
    ranking_weights: RankingWeights = Field(description="How offers are ranked.")
    can_auto_order: bool = Field(
        description="true: a cart within the limits is ordered with no approval. "
        "false: a person approves every cart.",
    )
    summary: list[str] = Field(description="The rules in plain sentences. Show them to the buyer.")


class MandateResponse(BaseModel):
    """`now` is the gateway clock. The agent resolves "Monday" from it, not from its own clock."""

    mandate: Mandate = Field(description="The buyer's rules.")
    now: datetime = Field(description="Gateway time. Resolve words such as Monday from it.")
    timezone: str = Field(description="Gateway time zone, Europe/Helsinki.")


class MandateUpdateRequest(RequestModel):
    """Only the fields to change. A missing field keeps its value."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"max_auto_order_value": "500.00"}]},
    )

    max_auto_order_value: Decimal | None = Field(
        default=None,
        ge=0,
        le=MAX_MANDATE_LIMIT,
        decimal_places=MONEY_DECIMALS,
        description="New automatic cart limit, EUR ex VAT. 0: proposals only.",
    )
    max_auto_value_per_delivery_date: Decimal | None = Field(
        default=None,
        ge=0,
        le=MAX_MANDATE_LIMIT,
        decimal_places=MONEY_DECIMALS,
        description="New limit per delivery date, EUR ex VAT.",
    )
    preferred_brands: list[str] | None = Field(default=None, description="New preferred brands.")
    required_attributes: list[AttributeCodeValue] | None = Field(
        default=None,
        description="New codes every product must have. [] clears the rule.",
    )
    forbidden_allergens: list[str] | None = Field(
        default=None,
        description="New forbidden allergen codes.",
    )
    allergen_unknown_policy: Decision | None = Field(
        default=None,
        description="New decision for UNKNOWN allergens.",
    )
    can_auto_order: bool | None = Field(
        default=None,
        description="true: let the agent order carts within the limits with no approval.",
    )

    def to_domain(self) -> MandateChanges:
        def as_tuple(values: list[str] | None) -> tuple[str, ...] | None:
            return None if values is None else tuple(values)

        return MandateChanges(
            max_auto_order_value=_cents(self.max_auto_order_value),
            max_auto_value_per_delivery_date=_cents(self.max_auto_value_per_delivery_date),
            preferred_brands=as_tuple(self.preferred_brands),
            required_attributes=as_tuple(self.required_attributes),
            forbidden_allergens=as_tuple(self.forbidden_allergens),
            allergen_unknown_policy=self.allergen_unknown_policy,
            can_auto_order=self.can_auto_order,
        )


def _cents(limit: Decimal | None) -> Decimal | None:
    """Input such as 1e6 or -0 passes the bounds but reads back as 1E+6 or -0. Store cents."""
    # abs() only clears the sign of -0: the bounds already refuse a negative limit.
    return None if limit is None else abs(round_money(limit))
