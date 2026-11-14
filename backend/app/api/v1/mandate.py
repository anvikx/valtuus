from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import MainUserDep, ServicesDep, require_scope
from app.api.results import mandate_response
from app.api.schemas.mandate import MandateResponse, MandateUpdateRequest
from app.domain.agent_key import AgentKey
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/mandate", tags=["mandate"])


@router.get("")
def get_mandate(
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CART))],
    services: ServicesDep,
) -> MandateResponse:
    mandate = services.mandates.get(agent.buyer_id)
    return mandate_response(services.mandates, mandate)


@router.put("")
def update_mandate(
    request: MandateUpdateRequest,
    user: MainUserDep,
    services: ServicesDep,
) -> MandateResponse:
    mandate = services.mandates.update(user, request.to_domain())
    return mandate_response(services.mandates, mandate)
