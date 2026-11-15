from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints

from app.domain.enums import AllergenStatus, ErrorCode, ReasonCode
from app.domain.errors import GatewayError
from app.domain.units import json_number

Quantity = Annotated[Decimal, PlainSerializer(json_number, when_used="json")]
# Far above any kitchen order. Without a cap, 1e27 overflowed the cent rounding into a 500.
_MAX_QUANTITY = 1_000_000
PositiveQuantity = Annotated[Quantity, Field(gt=0, le=_MAX_QUANTITY)]
PositiveSalesUnits = Annotated[int, Field(gt=0, le=_MAX_QUANTITY)]
CartRevisionValue = Annotated[int, Field(ge=1, strict=True)]
# One type for both doors: an empty key would match every retry and replay a wrong result.
IdempotencyKeyValue = Annotated[str, StringConstraints(min_length=1)]


class RequestModel(BaseModel):
    """Refuses unknown fields, so an agent cannot slip a price or a stock value into a call."""

    model_config = ConfigDict(extra="forbid")


class Allergens(BaseModel):
    status: AllergenStatus = Field(
        description="UNKNOWN when the product data does not declare its allergens. "
        "UNKNOWN never means safe.",
    )
    contains: list[str] = Field(
        description="Allergen codes the product contains or may contain.",
    )
    free_from: list[str] = Field(description="Allergen codes the product data marks as absent.")


class Reasons(BaseModel):
    """Every reason code comes with its sentence, in the same order."""

    reason_codes: list[ReasonCode] = Field(description="Why the gateway decided as it did.")
    reason_sentences: list[str] = Field(
        description="One plain sentence per reason code, in the same order. Show it to the buyer.",
    )


class ErrorBody(BaseModel):
    error: ErrorCode = Field(description="Machine code of the error.")
    message: str = Field(description="What went wrong, in one sentence.")
    next_step: str = Field(description="What the caller must do now.")
    reason_code: ReasonCode | None = Field(
        default=None,
        description="Only on NEEDS_CLARIFICATION: ask the buyer, do not guess a value.",
    )
    missing: list[str] | None = Field(
        default=None,
        description="Only with reason_code: the fields the buyer must give.",
        examples=[["lines[1].qty"]],
    )

    @classmethod
    def of(cls, exc: GatewayError) -> "ErrorBody":
        return cls(
            error=exc.code,
            message=exc.message,
            next_step=exc.next_step,
            reason_code=exc.reason_code,
            missing=list(exc.missing) or None,
        )
