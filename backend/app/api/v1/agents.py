from fastapi import APIRouter

from app.api.deps import HumanSessionDep, MainUserDep, Services, ServicesDep, buyer_of
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.schemas.agents import Agent

router = APIRouter(prefix="/v1/agents", tags=["agents"], responses=ERROR_RESPONSES)

_LIST = """
The buyer's agent keys and their status. Never the key or its hash.

**Request:** `GET /api/v1/agents`

**Auth:** main user session only.
"""
_REVOKE = """
Stop an agent: every active key of the agent becomes REVOKED. Its next call gets 401.
A second revoke changes nothing. Returns the buyer's agent list, as `GET /api/v1/agents`.

**Request:** `POST /api/v1/agents/{agent_id}/revoke`, no body.

**Auth:** main user session only. An agent key gets 403.
"""


@router.get("", description=describe(_LIST, Agent))
def list_agents(user: MainUserDep, services: ServicesDep) -> list[Agent]:
    return _agents(services, buyer_of(user))


@router.post("/{agent_id}/revoke", description=describe(_REVOKE, Agent))
def revoke_agent(agent_id: str, user: HumanSessionDep, services: ServicesDep) -> list[Agent]:
    buyer_id = buyer_of(user)
    services.agent_keys.revoke(buyer_id, agent_id, user.user_id)
    return _agents(services, buyer_id)


def _agents(services: Services, buyer_id: str) -> list[Agent]:
    agent_keys = services.agent_keys.list_for_buyer(buyer_id)
    return [Agent.model_validate(key, from_attributes=True) for key in agent_keys]
