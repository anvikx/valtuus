from fastapi import APIRouter

from app.api.deps import MainUserDep, ServicesDep, buyer_of
from app.api.docs import describe
from app.api.errors import ERROR_RESPONSES
from app.api.schemas.agents import Agent

router = APIRouter(prefix="/v1/agents", tags=["agents"], responses=ERROR_RESPONSES)

_LIST = """
The buyer's agent keys and their status. Never the key or its hash.

**Request:** `GET /api/v1/agents`

**Auth:** main user session only.
"""


@router.get("", description=describe(_LIST, Agent))
def list_agents(user: MainUserDep, services: ServicesDep) -> list[Agent]:
    agent_keys = services.agent_keys.list_for_buyer(buyer_of(user))
    return [Agent.model_validate(key, from_attributes=True) for key in agent_keys]
