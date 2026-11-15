from app.domain.enums import ErrorCode, ReasonCode
from app.domain.reason_text import reason_sentence


class GatewayError(Exception):
    """A technical error that the door turns into an HTTP error body. Never a decision."""

    code: ErrorCode
    # Set only when the agent must act on a reason, not only fix its call.
    reason_code: ReasonCode | None = None
    missing: tuple[str, ...] = ()

    def __init__(self, message: str, next_step: str) -> None:
        super().__init__(message)
        self.message = message
        self.next_step = next_step


class UnauthenticatedError(GatewayError):
    code = ErrorCode.UNAUTHENTICATED


class ForbiddenError(GatewayError):
    code = ErrorCode.FORBIDDEN


class NotFoundError(GatewayError):
    code = ErrorCode.NOT_FOUND


class ConflictError(GatewayError):
    code = ErrorCode.CONFLICT


class UpstreamUnavailableError(GatewayError):
    code = ErrorCode.UPSTREAM_UNAVAILABLE


class UpstreamRateLimitedError(UpstreamUnavailableError):
    """Valio Aimo paused our calls after a 429. The door sends retry_after as Retry-After."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "The Valio Aimo price or stock service paused our calls.",
            f"Try again in {retry_after} seconds.",
        )
        self.retry_after = retry_after


class InvalidRequestError(GatewayError):
    code = ErrorCode.VALIDATION_ERROR


class NeedsClarificationError(InvalidRequestError):
    """The request lacks a fact only the buyer knows. No cart, so a guess never becomes an order."""

    reason_code = ReasonCode.NEEDS_CLARIFICATION

    def __init__(self, missing: tuple[str, ...], question: str) -> None:
        super().__init__(
            reason_sentence(ReasonCode.NEEDS_CLARIFICATION, question=question),
            "Ask the buyer, then send the call again with the missing fields.",
        )
        self.missing = missing
