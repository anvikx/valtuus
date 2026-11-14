from typing import Any

from pydantic import BaseModel, Field

from app.api.schemas.common import RequestModel
from app.domain.signature import Verification, Verified, VerifyFailure, body_matches

# A signed order with many lines stays far below this. It keeps a large body from tying up a worker.
_MAX_JWS_LENGTH = 200_000


class VerifyRequest(RequestModel):
    jws: str = Field(
        max_length=_MAX_JWS_LENGTH,
        description="The `signature` of an offer or an order confirmation, as received.",
    )
    body: dict[str, Any] | None = Field(
        default=None,
        description="The body as shown, with or without its `signature` field. "
        "null: no comparison, and `body_matches` is null.",
    )


class VerifyResponse(BaseModel):
    valid: bool = Field(description="true: the gateway's key signed this payload, unchanged.")
    kid: str | None = Field(description="The key that signed it. null when not valid.")
    payload: dict[str, Any] | None = Field(
        description="The signed statement. Read the values from here, not from the shown body.",
    )
    body_matches: bool | None = Field(
        description="true: the sent body equals the payload. false: a shown value was changed. "
        "null: no body was sent, or the JWS is not valid. Show the trust mark only for valid "
        "and true.",
    )
    reason: VerifyFailure | None = Field(description="Why the JWS is not valid. null when valid.")

    @classmethod
    def of(cls, result: Verification, body: dict[str, Any] | None) -> "VerifyResponse":
        if not isinstance(result, Verified):
            return cls(valid=False, kid=None, payload=None, body_matches=None, reason=result.reason)

        return cls(
            valid=True,
            kid=result.kid,
            payload=dict(result.payload),
            body_matches=None if body is None else body_matches(result.payload, body),
            reason=None,
        )
