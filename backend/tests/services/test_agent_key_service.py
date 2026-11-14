import dataclasses

from app.adapters.memory.repositories import InMemoryAgentKeyRepository
from app.domain.agent_key import AgentKey, hash_agent_key
from app.domain.enums import AgentKeyStatus, AgentScope
from app.services.agent_key_service import AgentKeyService

_KEY = "test-agent-key-0123456789"
_ACTIVE = AgentKey(
    agent_id="claude-code",
    agent_name="claude-code",
    buyer_id="hotel-1",
    key_hash=hash_agent_key(_KEY),
    scopes=frozenset(AgentScope),
    status=AgentKeyStatus.ACTIVE,
)


def _service(agent_key: AgentKey) -> AgentKeyService:
    agent_keys = InMemoryAgentKeyRepository()
    agent_keys.add(agent_key)
    return AgentKeyService(agent_keys)


def test_active_key_authenticates() -> None:
    assert _service(_ACTIVE).authenticate(_KEY) == _ACTIVE


def test_unknown_key_is_refused() -> None:
    assert _service(_ACTIVE).authenticate("someone-elses-key") is None


def test_empty_key_is_refused() -> None:
    """A request with no key must never match a stored key."""
    assert _service(_ACTIVE).authenticate("") is None


def test_revoked_key_is_refused() -> None:
    """Revoking a key must stop the agent at once, not only on its next login."""
    revoked = dataclasses.replace(_ACTIVE, status=AgentKeyStatus.REVOKED)

    assert _service(revoked).authenticate(_KEY) is None


def test_buyer_sees_its_own_keys_and_revoked_ones_too() -> None:
    """The main user must see a revoked key to know the agent is cut off, and no other buyer's."""
    revoked = dataclasses.replace(
        _ACTIVE,
        agent_id="old-agent",
        key_hash=hash_agent_key("old-key"),
        status=AgentKeyStatus.REVOKED,
    )
    other = dataclasses.replace(_ACTIVE, buyer_id="hotel-2", key_hash=hash_agent_key("other"))
    agent_keys = InMemoryAgentKeyRepository()
    for agent_key in (_ACTIVE, revoked, other):
        agent_keys.add(agent_key)

    listed = AgentKeyService(agent_keys).list_for_buyer("hotel-1")

    assert sorted(key.agent_id for key in listed) == ["claude-code", "old-agent"]
