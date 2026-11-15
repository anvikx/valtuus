from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.api.schemas.common import ErrorBody
from app.domain.enums import ErrorCode
from app.domain.errors import GatewayError, UpstreamRateLimitedError

_STATUS = {
    ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.UNAUTHENTICATED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.FORBIDDEN: HTTPStatus.FORBIDDEN,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.UPSTREAM_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
}
# For the OpenAPI spec of each v1 router: every error status the handlers below can answer,
# with the body they really send. Built from _STATUS, so a new error code shows up by itself.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.value: {"model": ErrorBody, "description": status.phrase} for status in _STATUS.values()
}
# RFC 6750 section 3: a 401 names the scheme the client must use.
_CHALLENGE = {"WWW-Authenticate": "Bearer"}
# TODO: remove with its handler and the 501 test when no service raises NotImplementedError.
_NOT_IMPLEMENTED = {
    "error": "NOT_IMPLEMENTED",
    "message": "This operation is not built yet.",
    "next_step": "Try again after the next deploy.",
}


def error_response(body: ErrorBody) -> JSONResponse:
    status = _STATUS[body.error]
    headers = _CHALLENGE if status == HTTPStatus.UNAUTHORIZED else None
    # The two optional fields stay out of every body that does not use them.
    content = body.model_dump(mode="json", exclude_none=True)
    return JSONResponse(content, status_code=status, headers=headers)


async def _gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
    response = error_response(ErrorBody.of(exc))
    # RFC 9110 section 10.2.3: tells the agent when a retry can pass the Valio Aimo pause.
    if isinstance(exc, UpstreamRateLimitedError):
        response.headers["Retry-After"] = str(exc.retry_after)

    return response


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # The first problem is enough for the agent to fix its call.
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    body = ErrorBody(
        error=ErrorCode.VALIDATION_ERROR,
        message=f"{field}: {first['msg']}.",
        next_step="Fix the field and send the call again. Do not send fields that are not in "
        "the schema.",
    )
    return error_response(body)


async def _not_implemented(_: Request, __: NotImplementedError) -> JSONResponse:
    return JSONResponse(_NOT_IMPLEMENTED, status_code=HTTPStatus.NOT_IMPLEMENTED)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(GatewayError, _gateway_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(NotImplementedError, _not_implemented)
