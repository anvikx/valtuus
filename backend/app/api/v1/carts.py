from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.api.deps import HumanSessionDep, PublicUrlDep, ServicesDep, require_buyer, require_scope
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.results import cart_response, order_confirmation
from app.api.schemas.carts import CartRequest, CartResponse, RejectRequest
from app.api.schemas.common import IdempotencyKeyValue
from app.api.schemas.orders import OrderConfirmation
from app.domain.agent_key import AgentKey
from app.domain.constants import DUPLICATE_WINDOW_MINUTES, REJECT_MEMORY_MINUTES
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/carts", tags=["carts"], responses=ERROR_RESPONSES)

IdempotencyKey = Annotated[IdempotencyKeyValue, Header(alias="Idempotency-Key")]

_CREATE = f"""
Make a cart from offer lines. The gateway decides AUTO, HUMAN or DENY by the mandate.

**Request:** with an `Idempotency-Key` header.

```json
{{
  "lines": [{{"offer_id": "o_1", "product_id": "464306", "qty": 1000}}],
  "request_text": "1000 l lactose free milk for Monday"
}}
```

**Limit:** the same buyer, product, quantity and date inside {DUPLICATE_WINDOW_MINUTES} minutes is
DUPLICATE_ORDER. A cart the main user rejected inside {REJECT_MEMORY_MINUTES} minutes is
PREVIOUSLY_REJECTED.

**Scope:** `cart`.
"""
_GET = """
The cart and its current state. Poll it every 10 seconds while the main user decides.

**Request:** `GET /api/v1/carts/c_1`

**Auth:** an agent key with scope `cart`, or the main user session.
"""
_CHECKOUT = """
Place the order of an AUTO cart. The policy runs again with the current mandate.

**Request:** `POST /api/v1/carts/c_1/checkout` with an `Idempotency-Key` header.

**Limit:** HUMAN, DENY or EXPIRED returns 409. Send the same key on a retry.

**Scope:** `checkout`.
"""
_APPROVE = """
Approve a cart that waits for approval, and place its order. The policy runs again with the
current mandate.

**Request:** `POST /api/v1/carts/c_1/approve`

**Limit:** a second approve returns the same confirmation. A cart that is not approved, such as
an expired one, returns 409.

**Auth:** main user session only.
"""
_REJECT = """
Reject a cart that waits for approval, with a reason.

**Request:** `{"reason": "Too expensive."}`

**Auth:** main user session only.
"""


@router.post("", description=describe(_CREATE, CartResponse, CartRequest))
def create_cart(
    request: CartRequest,
    idempotency_key: IdempotencyKey,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    cart = services.carts.create_cart(agent, request.to_domain(), idempotency_key)
    return cart_response(cart, public_url)


@router.get("/{cart_id}", description=describe(_GET, CartResponse))
def get_cart(
    cart_id: str,
    buyer_id: Annotated[str, Depends(require_buyer(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    return cart_response(services.carts.get_cart(buyer_id, cart_id), public_url)


@router.post("/{cart_id}/checkout", description=describe(_CHECKOUT, OrderConfirmation))
def checkout(
    cart_id: str,
    idempotency_key: IdempotencyKey,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CHECKOUT))],
    services: ServicesDep,
) -> OrderConfirmation:
    return order_confirmation(services.orders.checkout(agent, cart_id, idempotency_key))


@router.post("/{cart_id}/approve", description=describe(_APPROVE, OrderConfirmation))
def approve(cart_id: str, user: HumanSessionDep, services: ServicesDep) -> OrderConfirmation:
    return order_confirmation(services.approvals.approve(user, cart_id))


@router.post(
    "/{cart_id}/reject",
    description=describe(_REJECT, CartResponse, RejectRequest),
)
def reject(
    cart_id: str,
    request: RejectRequest,
    user: HumanSessionDep,
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    return cart_response(services.approvals.reject(user, cart_id, request.reason), public_url)
