from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import AgentKeyStatus, AgentScope


class Agent(BaseModel):
    """Never the key or its hash."""

    agent_id: str = Field(description="Agent key id.")
    agent_name: str = Field(description="Name the main user gave the agent.")
    scopes: list[AgentScope] = Field(description="Operations the key may call.")
    status: AgentKeyStatus = Field(description="REVOKED keys get 401 on every call.")
    last_used_at: datetime | None = Field(description="Last call with the key. null: never used.")
