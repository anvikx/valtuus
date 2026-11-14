from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ServicesDep, require_buyer
from app.api.results import order_response
from app.api.schemas.orders import OrderConfirmation
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/orders", tags=["orders"])


@router.get("/{order_id}")
def get_order(
    order_id: str,
    buyer_id: Annotated[str, Depends(require_buyer(AgentScope.CART))],
    services: ServicesDep,
) -> OrderConfirmation:
    return order_response(services.orders.get_order(buyer_id, order_id))
