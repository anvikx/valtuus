from collections.abc import Sequence
from datetime import timedelta

from app.domain.agent_key import AgentKey, hash_agent_key
from app.domain.enums import AgentKeyStatus, AuditStep, ReasonCode
from app.domain.errors import NotFoundError
from app.services.audit_service import AuditService
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
        audit: AuditService,
        clock: Clock,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._agent_keys = agent_keys
        self._audit = audit
        self._clock = clock
        self._unit_of_work = unit_of_work

    def authenticate(self, presented_key: str) -> AgentKey | None:
        """The active key that matches, or None for a missing, unknown or revoked key."""
        if not presented_key:
            return None

        agent_key = self._agent_keys.by_hash(hash_agent_key(presented_key))
        if agent_key is None:
            return None

        if agent_key.status is not AgentKeyStatus.ACTIVE:
            self._record_revoked_call(agent_key)
            return None

        self._mark_used(agent_key)
        return agent_key

    def list_for_buyer(self, buyer_id: str) -> Sequence[AgentKey]:
        """Revoked keys too, so the main user sees which agents are cut off."""
        return self._agent_keys.for_buyer(buyer_id)

    def revoke(self, buyer_id: str, agent_id: str, actor: str) -> None:
        """Revokes every active key of the agent. A second revoke writes no second record.

        One agent can have more than one key: a new demo key leaves the old one, revoked.
        """
        with self._unit_of_work.transaction():
            owned = [key for key in self.list_for_buyer(buyer_id) if key.agent_id == agent_id]
            if not owned:
                raise NotFoundError(
                    f"Agent {agent_id} was not found.",
                    "Open the permissions page again and pick an agent from the list.",
                )

            revoked = [key for key in owned if self._agent_keys.revoke(key.key_hash)]
            if revoked:
                self._audit.record(
                    AuditStep.AGENT_REVOKED,
                    actor,
                    f"{actor} revoked {owned[0].agent_name}. Its next call is refused.",
                    buyer_id=buyer_id,
                    input_data={"agent_id": agent_id},
                )

    def _mark_used(self, agent_key: AgentKey) -> None:
        now = self._clock.now()
        cutoff = now - _USE_WRITE_INTERVAL
        if agent_key.last_used_at is not None and agent_key.last_used_at > cutoff:
            return

        with self._unit_of_work.transaction():
            self._agent_keys.mark_used(agent_key.key_hash, now, cutoff)

    def _record_revoked_call(self, agent_key: AgentKey) -> None:
        # ponytail: one record per refused call. Throttle like last_used_at if a revoked
        # agent that keeps polling fills the table.
        self._audit.record_refusal(
            agent_key.agent_id,
            f"{agent_key.agent_name} called with a revoked key. The gateway refused it.",
            ReasonCode.KEY_REVOKED,
            {"agent_id": agent_key.agent_id},
            buyer_id=agent_key.buyer_id,
        )
