import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import AgentKeyStatus, AgentScope, UserRole


def hash_agent_key(key: str) -> str:
    # The key is long and random, so a fast hash is safe. A slow password hash would only
    # add latency to every agent call.
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass(frozen=True)
class AgentKey:
    agent_id: str
    agent_name: str
    buyer_id: str
    key_hash: str
    scopes: frozenset[AgentScope]
    status: AgentKeyStatus
    last_used_at: datetime | None = None


@dataclass(frozen=True)
class User:
    user_id: str
    buyer_id: str | None
    role: UserRole
