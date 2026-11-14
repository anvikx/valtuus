from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import HumanSessionDep, ServicesDep, require_buyer
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.results import mandate_response
from app.api.schemas.mandate import MandateResponse, MandateUpdateRequest
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/mandate", tags=["mandate"], responses=ERROR_RESPONSES)

_GET = """
The buyer's rules and the gateway time. Read it before a search.

**Request:** `GET /api/v1/mandate`

**Auth:** agent key with scope `cart`, or the main user session.
"""
_UPDATE = """
Store a new version of the buyer's rules. Send only the fields to change.

**Request:** `{"max_auto_order_value": "500.00"}`

**Auth:** main user session only.
"""


@router.get("", description=describe(_GET, MandateResponse))
def get_mandate(
    buyer_id: Annotated[str, Depends(require_buyer(AgentScope.CART))],
    services: ServicesDep,
) -> MandateResponse:
    mandate = services.mandates.get(buyer_id)
    return mandate_response(services.mandates, mandate)


@router.put("", description=describe(_UPDATE, MandateResponse, MandateUpdateRequest))
def update_mandate(
    request: MandateUpdateRequest,
    user: HumanSessionDep,
    services: ServicesDep,
) -> MandateResponse:
    mandate = services.mandates.update(user, request.to_domain())
    return mandate_response(services.mandates, mandate)
