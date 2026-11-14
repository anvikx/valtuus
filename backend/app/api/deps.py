from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security.utils import get_authorization_scheme_param
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from app.api.errors import error_response
from app.api.schemas.common import ErrorBody
from app.domain.agent_key import AgentKey, User
from app.domain.enums import AgentScope, ErrorCode
from app.domain.errors import ForbiddenError, UnauthenticatedError
from app.services.agent_key_service import AgentKeyService
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.catalog_service import CatalogService
from app.services.mandate_service import MandateService
from app.services.offer_service import OfferService
from app.services.order_service import OrderService

_BEARER = "bearer"
_UNAUTHENTICATED = ErrorBody(
    error=ErrorCode.UNAUTHENTICATED,
    message="The agent key is missing, unknown or revoked.",
    next_step="Send the header Authorization: Bearer <agent key>. "
    "If the key was revoked, ask the main user for a new one.",
)


@dataclass(frozen=True)
class Services:
    """Built once in main.py. The REST and MCP doors call the same instances."""

    agent_keys: AgentKeyService
    catalog: CatalogService
    offers: OfferService
    carts: CartService
    orders: OrderService
    approvals: ApprovalService
    mandates: MandateService
    audit: AuditService


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


def get_public_url(request: Request) -> str:
    return request.app.state.public_url


PublicUrlDep = Annotated[str, Depends(get_public_url)]


def check_scope(agent_key: AgentKey, scope: AgentScope) -> None:
    """One check for both doors, so REST and MCP refuse the same calls."""
    if scope in agent_key.scopes:
        return

    # TODO: write the REFUSED audit record here, so the main user sees what the agent tried.
    raise ForbiddenError(
        f"The agent key has no {scope} scope.",
        "Ask the main user to grant the scope.",
    )


def require_scope(scope: AgentScope) -> Callable[[Request], AgentKey]:
    """REST dependency: the active agent key of the caller, with the given scope."""

    def dependency(request: Request) -> AgentKey:
        return _agent_key(request, scope)

    return dependency


def require_main_user() -> User:
    """The MAIN_USER session cookie. Login is not built yet."""
    raise NotImplementedError("main user session")


MainUserDep = Annotated[User, Depends(require_main_user)]


def require_buyer(scope: AgentScope) -> Callable[[Request], str]:
    """The buyer_id of an agent key with the scope, or of the main user session.

    The agent polls a cart and the main user opens the same cart on the approve page.
    """

    def dependency(request: Request) -> str:
        if _bearer_token(request.scope):
            return _agent_key(request, scope).buyer_id

        return buyer_of(require_main_user())

    return dependency


def buyer_of(user: User) -> str:
    """A user with no buyer (staff) has no carts, orders or agents to see."""
    if user.buyer_id is None:
        raise ForbiddenError(
            "This user acts for no buyer.",
            "Log in as the main user of the buyer.",
        )

    return user.buyer_id


def _agent_key(request: Request, scope: AgentScope) -> AgentKey:
    agent_key = get_services(request).agent_keys.authenticate(_bearer_token(request.scope))
    if agent_key is None:
        raise UnauthenticatedError(_UNAUTHENTICATED.message, _UNAUTHENTICATED.next_step)

    check_scope(agent_key, scope)
    return agent_key


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

        # The lookup can hit the database, so it must not block the event loop.
        agent_key = await run_in_threadpool(
            self._agent_key_service.authenticate,
            _bearer_token(scope),
        )
        if agent_key is None:
            await error_response(_UNAUTHENTICATED)(scope, receive, send)
            return

        # Tools read the caller from here for scope checks and audit records.
        scope.setdefault("state", {})["agent_key"] = agent_key
        await self._app(scope, receive, send)
