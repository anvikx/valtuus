from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints

from app.domain.enums import AllergenStatus, ErrorCode, ReasonCode


def _json_number(value: Decimal) -> int | float:
    # Quantities are JSON numbers (1000, 2.5). Only money and rates are strings.
    return int(value) if value == value.to_integral_value() else float(value)


Quantity = Annotated[Decimal, PlainSerializer(_json_number, when_used="json")]
PositiveQuantity = Annotated[Quantity, Field(gt=0)]
# One type for both doors: an empty key would match every retry and replay a wrong result.
IdempotencyKeyValue = Annotated[str, StringConstraints(min_length=1)]


class RequestModel(BaseModel):
    """Refuses unknown fields, so an agent cannot slip a price or a stock value into a call."""

    model_config = ConfigDict(extra="forbid")


class Allergens(BaseModel):
    status: AllergenStatus
    contains: list[str]
    free_from: list[str]


class Reasons(BaseModel):
    """Every reason code comes with its sentence, in the same order."""

    reason_codes: list[ReasonCode]
    reason_sentences: list[str]


class ErrorBody(BaseModel):
    error: ErrorCode
    message: str
    next_step: str
