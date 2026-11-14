from collections.abc import Sequence

from app.domain.agent_key import AgentKey, hash_agent_key
from app.domain.enums import AgentKeyStatus
from app.services.ports.repositories import AgentKeyRepository


class AgentKeyService:
    def __init__(self, agent_keys: AgentKeyRepository) -> None:
        self._agent_keys = agent_keys

    def authenticate(self, presented_key: str) -> AgentKey | None:
        """The active key that matches, or None for a missing, unknown or revoked key."""
        if not presented_key:
            return None

        agent_key = self._agent_keys.by_hash(hash_agent_key(presented_key))
        if agent_key is None or agent_key.status is not AgentKeyStatus.ACTIVE:
            return None

        return agent_key

    def list_for_buyer(self, buyer_id: str) -> Sequence[AgentKey]:
        raise NotImplementedError("AgentKeyService.list_for_buyer")
