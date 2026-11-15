from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import MainUserDep, ServicesDep, buyer_of, require_scope
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.results import offer_response
from app.api.schemas.offers import OfferRequest, OfferResponse
from app.domain.agent_key import AgentKey
from app.domain.constants import OFFER_TTL_MINUTES
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/offers", tags=["offers"], responses=ERROR_RESPONSES)

_OFFERS = f"""
Live price and stock from Valio Aimo for chosen products, ranked by the mandate.

**Request:**

```json
{{"product_ids": ["464306"], "quantity": 1000, "unit": "L", "deliver_by": "2026-11-16"}}
```

Send all candidates from the search. The stock snapshot is valid for {OFFER_TTL_MINUTES}
minutes (`valid_until`). The price holds until `price_valid_to`.
Rank full on-time stock first, partial or unconfirmed stock next, and late products last.
Within each group, prioritize preferred brands, then price per requested unit.
A brand outside the mandate preference requires human approval.

**Scope:** `offer`.
"""
_GET = """
A stored offer with its `signature`, for the approval page to check the cart's prices.

**Request:** `GET /api/v1/offers/{offer_id}`

**Auth:** main user session only. The agent has the offer from `POST /api/v1/offers`.
"""


@router.post("", description=describe(_OFFERS, OfferResponse, OfferRequest))
def get_offers(
    request: OfferRequest,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.OFFER))],
    services: ServicesDep,
) -> OfferResponse:
    return offer_response(services.offers.get_offers(agent, request.to_domain()))


@router.get("/{offer_id}", description=describe(_GET, OfferResponse))
def read_offer(offer_id: str, user: MainUserDep, services: ServicesDep) -> OfferResponse:
    return offer_response(services.offers.get_offer(buyer_of(user), offer_id))
