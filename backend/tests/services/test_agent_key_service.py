import dataclasses
from datetime import UTC, datetime, timedelta

from app.adapters.memory.repositories import InMemoryAgentKeyRepository, InMemoryUnitOfWork
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
_POLL_INTERVAL = timedelta(seconds=5)


class _Clock:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 14, 12, tzinfo=UTC)

    def now(self) -> datetime:
        return self.at


class _CountingAgentKeys(InMemoryAgentKeyRepository):
    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def mark_used(self, key_hash: str, at: datetime, cutoff: datetime) -> None:
        self.writes += 1
        super().mark_used(key_hash, at, cutoff)


def _service(
    agent_key: AgentKey,
    clock: _Clock | None = None,
    agent_keys: InMemoryAgentKeyRepository | None = None,
) -> AgentKeyService:
    agent_keys = agent_keys or InMemoryAgentKeyRepository()
    agent_keys.add(agent_key)
    return AgentKeyService(agent_keys, clock or _Clock(), InMemoryUnitOfWork())


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


def test_ten_polls_in_one_minute_write_the_time_once() -> None:
    """An agent polls every few seconds. The page shows the minute, so more writes add only load."""
    clock = _Clock()
    agent_keys = _CountingAgentKeys()
    service = _service(_ACTIVE, clock, agent_keys)
    first_poll = clock.at

    for _ in range(10):
        service.authenticate(_KEY)
        clock.at += _POLL_INTERVAL

    assert agent_keys.writes == 1
    stored = agent_keys.by_hash(_ACTIVE.key_hash)
    assert stored is not None
    assert stored.last_used_at == first_poll


def test_call_a_minute_later_writes_the_time_again() -> None:
    """Without a new write, the page would show an agent that still works as idle."""
    clock = _Clock()
    agent_keys = InMemoryAgentKeyRepository()
    service = _service(_ACTIVE, clock, agent_keys)
    service.authenticate(_KEY)
    clock.at += timedelta(minutes=1)

    service.authenticate(_KEY)

    stored = agent_keys.by_hash(_ACTIVE.key_hash)
    assert stored is not None
    assert stored.last_used_at == clock.at


def test_refused_key_gets_no_use_time() -> None:
    """A revoked key that keeps calling must not look active on the page."""
    revoked = dataclasses.replace(_ACTIVE, status=AgentKeyStatus.REVOKED)
    agent_keys = InMemoryAgentKeyRepository()
    service = _service(revoked, agent_keys=agent_keys)

    service.authenticate(_KEY)

    stored = agent_keys.by_hash(_ACTIVE.key_hash)
    assert stored is not None
    assert stored.last_used_at is None


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

    listed = _service(_ACTIVE, agent_keys=agent_keys).list_for_buyer("hotel-1")

    assert sorted(key.agent_id for key in listed) == ["claude-code", "old-agent"]
