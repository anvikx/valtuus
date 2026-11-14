from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ServicesDep, require_buyer
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.results import order_response
from app.api.schemas.orders import OrderConfirmation
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/orders", tags=["orders"], responses=ERROR_RESPONSES)

_GET = """
A placed order.

**Request:** `GET /api/v1/orders/{order_id}`

**Auth:** an agent key with scope `cart`, or the main user session.
"""


@router.get("/{order_id}", description=describe(_GET, OrderConfirmation))
def get_order(
    order_id: str,
    buyer_id: Annotated[str, Depends(require_buyer(AgentScope.CART))],
    services: ServicesDep,
) -> OrderConfirmation:
    return order_response(services.orders.get_order(buyer_id, order_id))
