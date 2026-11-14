import dataclasses
from decimal import Decimal

import pytest

from app.adapters.memory import (
    InMemoryAgentKeyRepository,
    InMemoryMandateRepository,
    InMemoryUserRepository,
)
from app.domain.access import hash_agent_key
from app.domain.enums import AgentScope, UserRole
from app.services.seed import DEMO_BUYER_ID, DEMO_MAIN_USER_ID, seed_demo

_KEY = "test-agent-key-0123456789"


def _seeded() -> tuple[
    InMemoryMandateRepository,
    InMemoryAgentKeyRepository,
    InMemoryUserRepository,
]:
    repos = (
        InMemoryMandateRepository(),
        InMemoryAgentKeyRepository(),
        InMemoryUserRepository(),
    )
    seed_demo(*repos, agent_key=_KEY)
    return repos


def test_seed_starts_hotel_1_at_the_500_limit() -> None:
    """A 1,010.00 EUR order must need approval, so version 1 allows only 500.00."""
    mandates, _, _ = _seeded()

    mandate = mandates.latest(DEMO_BUYER_ID)

    assert mandate is not None
    assert mandate.version == 1
    assert mandate.max_auto_order_value == Decimal("500.00")
    assert mandate.max_auto_value_per_delivery_date == Decimal("500.00")


def test_seed_stores_the_agent_key_only_as_a_hash() -> None:
    """A leaked store must not give an attacker a working key."""
    _, agent_keys, _ = _seeded()

    agent = agent_keys.by_hash(hash_agent_key(_KEY))

    assert agent is not None
    assert agent.scopes == frozenset(AgentScope)
    assert _KEY not in repr(dataclasses.astuple(agent))


def test_seed_refuses_an_empty_agent_key() -> None:
    """An empty key would let any caller that sends no key act as the agent."""
    with pytest.raises(ValueError, match="empty"):
        seed_demo(
            InMemoryMandateRepository(),
            InMemoryAgentKeyRepository(),
            InMemoryUserRepository(),
            agent_key="",
        )


def test_seed_adds_the_main_user() -> None:
    """Only the main user may approve, so the seed must contain one."""
    _, _, users = _seeded()

    user = users.get(DEMO_MAIN_USER_ID)

    assert user is not None
    assert user.role is UserRole.MAIN_USER


def test_mandate_repository_refuses_a_version_gap_or_overwrite() -> None:
    """Old versions stay, so an order can always name the rules it ran under."""
    mandates, _, _ = _seeded()
    current = mandates.latest(DEMO_BUYER_ID)
    assert current is not None

    with pytest.raises(ValueError, match="version must be 2"):
        mandates.add(current)

    mandates.add(dataclasses.replace(current, version=2))
    latest = mandates.latest(DEMO_BUYER_ID)
    assert latest is not None
    assert latest.version == 2
