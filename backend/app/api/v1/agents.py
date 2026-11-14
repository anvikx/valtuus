from fastapi import APIRouter

from app.api.deps import MainUserDep, ServicesDep, buyer_of
from app.api.schemas.agents import Agent

router = APIRouter(prefix="/v1/agents", tags=["agents"])


@router.get("")
def list_agents(user: MainUserDep, services: ServicesDep) -> list[Agent]:
    agent_keys = services.agent_keys.list_for_buyer(buyer_of(user))
    return [Agent.model_validate(key, from_attributes=True) for key in agent_keys]
