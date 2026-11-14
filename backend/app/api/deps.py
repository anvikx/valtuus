from http import HTTPStatus

from fastapi.security.utils import get_authorization_scheme_param
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.schemas.common import ErrorBody
from app.domain.enums import ErrorCode
from app.services.agent_key_service import AgentKeyService

_BEARER = "bearer"
# RFC 6750 section 3: a 401 names the scheme the client must use.
_CHALLENGE = {"WWW-Authenticate": "Bearer"}
_UNAUTHENTICATED = ErrorBody(
    error=ErrorCode.UNAUTHENTICATED,
    message="The agent key is missing, unknown or revoked.",
    next_step="Send the header Authorization: Bearer <agent key>. "
    "If the key was revoked, ask the main user for a new one.",
)


def _bearer_token(scope: Scope) -> str:
    scheme, token = get_authorization_scheme_param(Headers(scope=scope).get("Authorization"))
    return token if scheme.lower() == _BEARER else ""


class AgentKeyGuard:
    """Refuses every HTTP call to the wrapped app that has no active agent key."""

    def __init__(self, app: ASGIApp, agent_key_service: AgentKeyService) -> None:
        self._app = app
        self._agent_key_service = agent_key_service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        # ponytail: sync lookup on the event loop is fine for the in-memory store.
        # Move it to a thread when the Postgres repository lands.
        agent_key = self._agent_key_service.authenticate(_bearer_token(scope))
        if agent_key is None:
            response = JSONResponse(
                _UNAUTHENTICATED.model_dump(mode="json"),
                status_code=HTTPStatus.UNAUTHORIZED,
                headers=_CHALLENGE,
            )
            await response(scope, receive, send)
            return

        # Tools read the caller from here for scope checks and audit records.
        scope.setdefault("state", {})["agent_key"] = agent_key
        await self._app(scope, receive, send)
