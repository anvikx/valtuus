from datetime import datetime

from pydantic import BaseModel

from app.domain.enums import AgentKeyStatus, AgentScope


class Agent(BaseModel):
    """Never the key or its hash."""

    agent_id: str
    agent_name: str
    scopes: list[AgentScope]
    status: AgentKeyStatus
    last_used_at: datetime | None
