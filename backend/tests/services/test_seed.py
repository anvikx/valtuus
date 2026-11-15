import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.adapters.memory.repositories import (
    InMemoryAgentKeyRepository,
    InMemoryMandateRepository,
    InMemoryOrderRepository,
    InMemoryUnitOfWork,
    InMemoryUserRepository,
)
from app.domain.agent_key import hash_agent_key
from app.domain.enums import AgentKeyStatus, AgentScope, UserRole
from app.domain.policy.baseline import build_baseline
from app.domain.policy.check import PolicyContext
from app.domain.policy.checks.envelope import KnownProduct, Quantity
from app.services.seed import DEMO_BUYER_ID, DEMO_MAIN_USER_ID, seed_demo

_KEY = "test-agent-key-0123456789"
_NEW_KEY = "test-agent-key-rotated-9876"
_DEMO_MILK_ID = "464306"
# Run 2 asks for 20 L of 464306, sold per 1 l pack.
_RUN_2_QTY = 20


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
    seed_demo(*repos, InMemoryUnitOfWork(), agent_key=_KEY, orders=InMemoryOrderRepository())
    return repos


def _reseed(
    repos: tuple[InMemoryMandateRepository, InMemoryAgentKeyRepository, InMemoryUserRepository],
    agent_key: str = _KEY,
) -> None:
    """The same seed a restart runs on a store that kept its data."""
    seed_demo(*repos, InMemoryUnitOfWork(), agent_key=agent_key, orders=InMemoryOrderRepository())


def _status(agent_keys: InMemoryAgentKeyRepository, key: str) -> AgentKeyStatus:
    agent = agent_keys.by_hash(hash_agent_key(key))
    assert agent is not None
    return agent.status


def test_seed_starts_hotel_1_at_the_500_limit() -> None:
    """A 1,010.00 EUR order must need approval, so version 1 allows only 500.00."""
    mandates, _, _ = _seeded()

    mandate = mandates.latest(DEMO_BUYER_ID)

    assert mandate is not None
    assert mandate.version == 1
    assert mandate.max_auto_order_value == Decimal("500.00")
    assert mandate.max_auto_value_per_delivery_date == Decimal("500.00")


def test_seed_starts_hotel_1_with_automatic_orders_off() -> None:
    """The main user must turn on automatic orders before the agent may spend alone."""
    mandates, _, _ = _seeded()

    mandate = mandates.latest(DEMO_BUYER_ID)

    assert mandate is not None
    assert mandate.can_auto_order is False


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
            InMemoryUnitOfWork(),
            agent_key="",
            orders=InMemoryOrderRepository(),
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


def test_reseed_keeps_a_newer_mandate() -> None:
    """A restart must not reset the limits the main user raised."""
    repos = _seeded()
    mandates, _, _ = repos
    current = mandates.latest(DEMO_BUYER_ID)
    assert current is not None
    mandates.add(dataclasses.replace(current, version=2))

    _reseed(repos)

    latest = mandates.latest(DEMO_BUYER_ID)
    assert latest is not None
    assert latest.version == 2


def test_reseed_keeps_a_revoked_key_revoked() -> None:
    """A restart must not give a revoked agent its access back."""
    repos = _seeded()
    _, agent_keys, _ = repos
    agent = agent_keys.by_hash(hash_agent_key(_KEY))
    assert agent is not None
    agent_keys.add(dataclasses.replace(agent, status=AgentKeyStatus.REVOKED))

    _reseed(repos)

    assert _status(agent_keys, _KEY) is AgentKeyStatus.REVOKED


def test_new_agent_key_revokes_the_old_one() -> None:
    """A key rotated in .env replaces the old key, so a leaked old key stops working."""
    repos = _seeded()
    _, agent_keys, _ = repos

    _reseed(repos, agent_key=_NEW_KEY)

    assert _status(agent_keys, _KEY) is AgentKeyStatus.REVOKED
    assert _status(agent_keys, _NEW_KEY) is AgentKeyStatus.ACTIVE


def _seed_with_orders(orders: InMemoryOrderRepository) -> InMemoryMandateRepository:
    mandates = InMemoryMandateRepository()
    seed_demo(
        mandates,
        InMemoryAgentKeyRepository(),
        InMemoryUserRepository(),
        InMemoryUnitOfWork(),
        agent_key=_KEY,
        orders=orders,
    )
    return mandates


def test_seed_lets_run_2_pass_the_envelope_on_a_fresh_store() -> None:
    """Run 2 (20 L) must be AUTO without an approved run 1 first, as the demo shows it."""
    orders = InMemoryOrderRepository()
    mandates = _seed_with_orders(orders)
    context = PolicyContext(
        mandate=mandates.latest(DEMO_BUYER_ID),
        day_orders=(),
        recent_rejects=(),
        now=datetime.now(UTC),
        baseline=build_baseline(orders.list_confirmed(DEMO_BUYER_ID)),
    )
    run_2 = SimpleNamespace(product_id=_DEMO_MILK_ID, name="milk", qty=_RUN_2_QTY)

    results = [*KnownProduct().evaluate([run_2], context), *Quantity().evaluate([run_2], context)]

    assert results == []


def test_seed_history_is_approved_by_the_main_user() -> None:
    """Only orders a person approved may widen what the agent can repeat alone."""
    orders = InMemoryOrderRepository()
    _seed_with_orders(orders)

    confirmed = orders.list_confirmed(DEMO_BUYER_ID)

    assert len(confirmed) == 3
    assert {order.approved_by for order in confirmed} == {DEMO_MAIN_USER_ID}


def test_reseed_adds_no_second_history() -> None:
    """A restart must not double the history, or the baseline would count each order twice."""
    orders = InMemoryOrderRepository()
    _seed_with_orders(orders)

    _seed_with_orders(orders)

    assert len(orders.list_confirmed(DEMO_BUYER_ID)) == 3
