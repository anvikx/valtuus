from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ServicesDep, require_scope
from app.api.results import search_response
from app.api.schemas.catalog import SearchRequest, SearchResponse
from app.domain.agent_key import AgentKey
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


@router.get("/search")
def search_products(
    request: Annotated[SearchRequest, Query()],
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CATALOG_READ))],
    services: ServicesDep,
) -> SearchResponse:
    return search_response(services.catalog.search(agent, request.to_domain()))
