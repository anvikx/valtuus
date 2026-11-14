from app.domain.enums import ErrorCode


class GatewayError(Exception):
    """A technical error that the door turns into an HTTP error body. Never a decision."""

    code: ErrorCode

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
