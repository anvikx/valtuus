from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import ServicesDep, require_scope
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.results import search_response
from app.api.schemas.catalog import SearchRequest, SearchResponse
from app.domain.agent_key import AgentKey
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/catalog", tags=["catalog"], responses=ERROR_RESPONSES)

_SEARCH = """
Search the product file. No price and no stock: send the candidates to get_offers.

**Request:**

```
GET /api/v1/catalog/search?query=milk&required_attributes=FREE_FROM_LACTOSE
    &quantity=1000&unit=L&deliver_by=2026-11-16
```

Return every match of the requested category, or the category with the most hits.
Only the configurable safety guard can cut the category. `total_hits` and the top-eight
`categories` summary count all filtered hits before that guard. Each category includes its
hit count and up to two distinct example product names.

`understood` holds the normalized request. Follow the single `hint` advice code:
EXCLUDED_ONLY, NO_MATCH, MISSING_FIELDS, GUARD_CUT or READY. READY means the category is
complete; it does not identify the buyer's intended type. Use `category` to select another.
Ask for `missing_fields` before offers. Send `request_id` with get_offers.

**Scope:** `catalog:read`.
"""


@router.get("/search", description=describe(_SEARCH, SearchResponse, SearchRequest))
def search_products(
    request: Annotated[SearchRequest, Query()],
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.CATALOG_READ))],
    services: ServicesDep,
) -> SearchResponse:
    return search_response(services.catalog.search(agent, request.to_domain()))
