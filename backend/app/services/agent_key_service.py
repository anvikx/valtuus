from collections.abc import Sequence
from datetime import timedelta

from app.domain.agent_key import AgentKey, hash_agent_key
from app.domain.enums import AgentKeyStatus
from app.services.ports.clock import Clock
from app.services.ports.repositories import AgentKeyRepository
from app.services.ports.unit_of_work import UnitOfWork

# The page shows the minute of the last call, so an agent that polls every few seconds
# needs one write a minute, not one per call.
_USE_WRITE_INTERVAL = timedelta(minutes=1)


class AgentKeyService:
    def __init__(
        self,
        agent_keys: AgentKeyRepository,
        clock: Clock,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._agent_keys = agent_keys
        self._clock = clock
        self._unit_of_work = unit_of_work

    def authenticate(self, presented_key: str) -> AgentKey | None:
        """The active key that matches, or None for a missing, unknown or revoked key."""
        if not presented_key:
            return None

        agent_key = self._agent_keys.by_hash(hash_agent_key(presented_key))
        if agent_key is None or agent_key.status is not AgentKeyStatus.ACTIVE:
            return None

        self._mark_used(agent_key)
        return agent_key

    def list_for_buyer(self, buyer_id: str) -> Sequence[AgentKey]:
        """Revoked keys too, so the main user sees which agents are cut off."""
        return self._agent_keys.for_buyer(buyer_id)

    def _mark_used(self, agent_key: AgentKey) -> None:
        now = self._clock.now()
        cutoff = now - _USE_WRITE_INTERVAL
        if agent_key.last_used_at is not None and agent_key.last_used_at > cutoff:
            return

        with self._unit_of_work.transaction():
            self._agent_keys.mark_used(agent_key.key_hash, now, cutoff)
