from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.api.deps import MainUserDep, PublicUrlDep, ServicesDep, require_buyer, require_scope
from app.api.results import cart_response, order_confirmation
from app.api.schemas.carts import CartRequest, CartResponse, RejectRequest
from app.api.schemas.common import IdempotencyKeyValue
from app.api.schemas.orders import OrderConfirmation
from app.domain.agent_key import AgentKey
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/carts", tags=["carts"])

IdempotencyKey = Annotated[IdempotencyKeyValue, Header(alias="Idempotency-Key")]


@router.post("")
def create_cart(
    request: CartRequest,
    idempotency_key: IdempotencyKey,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    cart = services.carts.create_cart(agent, request.to_domain(), idempotency_key)
    return cart_response(cart, public_url)


@router.get("/{cart_id}")
def get_cart(
    cart_id: str,
    buyer_id: Annotated[str, Depends(require_buyer(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    return cart_response(services.carts.get_cart(buyer_id, cart_id), public_url)


@router.post("/{cart_id}/checkout")
def checkout(
    cart_id: str,
    idempotency_key: IdempotencyKey,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CHECKOUT))],
    services: ServicesDep,
) -> OrderConfirmation:
    return order_confirmation(services.orders.checkout(agent, cart_id, idempotency_key))


@router.post("/{cart_id}/approve")
def approve(cart_id: str, user: MainUserDep, services: ServicesDep) -> OrderConfirmation:
    return order_confirmation(services.approvals.approve(user, cart_id))


@router.post("/{cart_id}/reject")
def reject(
    cart_id: str,
    request: RejectRequest,
    user: MainUserDep,
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    return cart_response(services.approvals.reject(user, cart_id, request.reason), public_url)
