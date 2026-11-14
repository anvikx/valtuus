from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.api.schemas.common import ErrorBody
from app.domain.enums import ErrorCode
from app.domain.errors import GatewayError

_STATUS = {
    ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.UNAUTHENTICATED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.FORBIDDEN: HTTPStatus.FORBIDDEN,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.UPSTREAM_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
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
    return JSONResponse(body.model_dump(mode="json"), status_code=status, headers=headers)


async def _gateway_error(_: Request, exc: GatewayError) -> JSONResponse:
    return error_response(ErrorBody(error=exc.code, message=exc.message, next_step=exc.next_step))


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
