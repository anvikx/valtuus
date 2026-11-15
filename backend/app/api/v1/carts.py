from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query

from app.api.deps import (
    HumanSessionDep,
    MainUserDep,
    PublicUrlDep,
    ServicesDep,
    buyer_of,
    require_buyer,
    require_scope,
)
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.results import cart_details_response, cart_response, order_confirmation
from app.api.schemas.carts import (
    CartActionRequest,
    CartDetailsResponse,
    CartRequest,
    CartResponse,
    RejectRequest,
    RevisionRequest,
)
from app.api.schemas.common import IdempotencyKeyValue
from app.api.schemas.orders import OrderConfirmation
from app.domain.agent_key import AgentKey
from app.domain.constants import DUPLICATE_WINDOW_MINUTES, REJECT_MEMORY_MINUTES
from app.domain.enums import AgentScope
from app.services.decision_waiter import HOLD_SECONDS

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
_REVISE = """
Change the lines of an open cart. This makes the next revision and runs the policy again, so
an AUTO cart can need approval and a pending cart can become AUTO. The old revision stays on
the record.

**Request:** with an `Idempotency-Key` header and the revision you changed.

```json
{
  "base_revision": 1,
  "lines": [{"offer_id": "o_1", "product_id": "464306", "qty": 800}],
  "request_text": "make it 800"
}
```

**Limit:** AUTO and PENDING_APPROVAL only. Any other state returns 409. A base_revision that
is not the current one returns 409: read the cart and send the change again.

**Scope:** `cart`.
"""
_WITHDRAW = """
Withdraw an open cart when the buyer no longer wants it. WITHDRAWN is final, and the main user
can no longer approve it.

**Request:** `POST /api/v1/carts/c_1/withdraw`

**Limit:** AUTO and PENDING_APPROVAL only. Any other state returns 409.

**Scope:** `cart`.
"""
_LIST = """
The approval inbox: the buyer's carts, each in its current state. Carts that wait for the main
user come first, the earliest deadline on top. Then the other carts, the latest first.

**Request:** `GET /api/v1/carts`

**Auth:** main user session only.
"""
_GET = """
The cart and its current state, revision number, revision count and line changes
from the immediately preceding revision (N-1). An unchanged read adds no history or audit record.
To wait for the main user's decision, use `GET /api/v1/carts/c_1/wait`.

**Request:** `GET /api/v1/carts/c_1`

**Auth:** an agent key with scope `cart`, or the main user session.
"""
_WAIT = f"""
Hold the read while the main user decides on a pending cart, so the agent needs no timer.
It returns the cart as soon as the state or the revision changes, or `current_decision`
becomes AUTO. Else it returns the pending cart after about {HOLD_SECONDS:.0f} seconds: call
it again.

**Request:** `GET /api/v1/carts/c_1/wait?revision=1` with the revision of your last read.

**Auth:** an agent key with scope `cart`, or the main user session.
"""
_CHECKOUT = """
Place the order of an AUTO cart, or of a pending cart that the current mandate now allows.
The policy runs again with the current mandate.

**Request:** `POST /api/v1/carts/c_1/checkout` with an `Idempotency-Key` header
and body `{"revision": 1}` from the cart you reviewed. A stale revision returns 409.
Read and review the current cart before sending its revision.

**Limit:** HUMAN, DENY or EXPIRED returns 409, and the cart keeps that new state. After the
15 minutes of the offer, a changed price or too little stock gives EXPIRED. Send the same
key on a retry to get the same order. A new key on an ORDERED cart returns 409.

**Scope:** `checkout`.
"""
_APPROVE = """
Approve a cart that waits for approval, and place its order. The policy runs again with the
current mandate.

**Request:** `POST /api/v1/carts/c_1/approve` with body `{"revision": 1}` from the cart
you reviewed. A stale revision returns 409. Read and review the current cart again.

**Limit:** a second approve returns the same confirmation. A cart that is not approved, such as
an expired one, returns 409.

**Auth:** main user session only.
"""
_REJECT = """
Reject a cart that waits for approval, with a reason.

**Request:** `{"revision": 1, "reason": "Too expensive."}`. A stale revision returns 409.
Read and review the current cart before rejecting it.

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


@router.get("", description=describe(_LIST, CartResponse))
def list_carts(
    user: MainUserDep,
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> list[CartResponse]:
    carts = services.carts.list_for_inbox(buyer_of(user))
    return [cart_response(cart, public_url) for cart in carts]


@router.get("/{cart_id}", description=describe(_GET, CartDetailsResponse))
def get_cart(
    cart_id: str,
    buyer_id: Annotated[str, Depends(require_buyer(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartDetailsResponse:
    return cart_details_response(services.carts.get_cart_details(buyer_id, cart_id), public_url)


@router.get("/{cart_id}/wait", description=describe(_WAIT, CartDetailsResponse))
async def wait_for_decision(
    cart_id: str,
    revision: Annotated[int, Query(ge=1)],
    buyer_id: Annotated[str, Depends(require_buyer(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartDetailsResponse:
    details = await services.decisions.wait(buyer_id, cart_id, revision)
    return cart_details_response(details, public_url)


@router.post("/{cart_id}/revisions", description=describe(_REVISE, CartResponse, RevisionRequest))
def revise_cart(
    cart_id: str,
    request: RevisionRequest,
    idempotency_key: IdempotencyKey,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    draft = request.to_domain()
    cart = services.carts.revise_cart(
        agent,
        cart_id,
        request.base_revision,
        draft,
        idempotency_key,
    )
    return cart_response(cart, public_url)


@router.post("/{cart_id}/withdraw", description=describe(_WITHDRAW, CartResponse))
def withdraw_cart(
    cart_id: str,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CART))],
    services: ServicesDep,
    public_url: PublicUrlDep,
) -> CartResponse:
    return cart_response(services.carts.withdraw_cart(agent, cart_id), public_url)


@router.post(
    "/{cart_id}/checkout", description=describe(_CHECKOUT, OrderConfirmation, CartActionRequest)
)
def checkout(
    cart_id: str,
    request: CartActionRequest,
    idempotency_key: IdempotencyKey,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CHECKOUT))],
    services: ServicesDep,
) -> OrderConfirmation:
    return order_confirmation(
        services.orders.checkout(agent, cart_id, request.revision, idempotency_key)
    )


@router.post(
    "/{cart_id}/approve", description=describe(_APPROVE, OrderConfirmation, CartActionRequest)
)
def approve(
    cart_id: str,
    request: CartActionRequest,
    user: HumanSessionDep,
    services: ServicesDep,
) -> OrderConfirmation:
    return order_confirmation(services.approvals.approve(user, cart_id, request.revision))


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
    return cart_response(
        services.approvals.reject(user, cart_id, request.revision, request.reason), public_url
    )
