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
