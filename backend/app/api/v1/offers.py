from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ServicesDep, require_scope
from app.api.results import offer_response
from app.api.schemas.offers import OfferRequest, OfferResponse
from app.domain.agent_key import AgentKey
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/offers", tags=["offers"])


@router.post("")
def get_offers(
    request: OfferRequest,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.OFFER))],
    services: ServicesDep,
) -> OfferResponse:
    return offer_response(services.offers.get_offers(agent, request.to_domain()))
