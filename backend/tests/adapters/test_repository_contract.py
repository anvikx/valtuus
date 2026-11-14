"""One behaviour, two adapters: each test runs on the memory and on the Postgres store."""

import dataclasses
from dataclasses import dataclass
from datetime import timedelta

import pytest

from app.adapters.memory.repositories import (
    InMemoryAgentKeyRepository,
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryIdempotencyRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemoryUnitOfWork,
    InMemoryUserRepository,
)
from app.adapters.postgres.repositories import (
    PostgresAgentKeyRepository,
    PostgresAuditRepository,
    PostgresCartRepository,
    PostgresIdempotencyRepository,
    PostgresMandateRepository,
    PostgresOfferRepository,
    PostgresOrderRepository,
    PostgresUserRepository,
)
from app.domain.agent_key import User
from app.domain.enums import AgentKeyStatus, CartState, UserRole
from app.domain.idempotency import IdempotencyRecord
from app.services.ports.repositories import (
    AgentKeyRepository,
    AuditRepository,
    CartRepository,
    IdempotencyRepository,
    MandateRepository,
    OfferRepository,
    OrderRepository,
    UserRepository,
)
from app.services.ports.unit_of_work import UnitOfWork
from tests.adapters import samples


@dataclass(frozen=True)
class _Store:
    mandates: MandateRepository
    agent_keys: AgentKeyRepository
    users: UserRepository
    offers: OfferRepository
    carts: CartRepository
    orders: OrderRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository
    unit_of_work: UnitOfWork


def _memory_store() -> _Store:
    return _Store(
        mandates=InMemoryMandateRepository(),
        agent_keys=InMemoryAgentKeyRepository(),
        users=InMemoryUserRepository(),
        offers=InMemoryOfferRepository(),
        carts=InMemoryCartRepository(),
        orders=InMemoryOrderRepository(),
        audit=InMemoryAuditRepository(),
        idempotency=InMemoryIdempotencyRepository(),
        unit_of_work=InMemoryUnitOfWork(),
    )


def _postgres_store(request: pytest.FixtureRequest) -> _Store:
    database = request.getfixturevalue("database")
    return _Store(
        mandates=PostgresMandateRepository(database),
        agent_keys=PostgresAgentKeyRepository(database),
        users=PostgresUserRepository(database),
        offers=PostgresOfferRepository(database),
        carts=PostgresCartRepository(database),
        orders=PostgresOrderRepository(database),
        audit=PostgresAuditRepository(database),
        idempotency=PostgresIdempotencyRepository(database),
        unit_of_work=database,
    )


@pytest.fixture(params=["memory", "postgres"])
def store(request: pytest.FixtureRequest) -> _Store:
    if request.param == "memory":
        return _memory_store()

    return _postgres_store(request)


def test_mandate_round_trip_keeps_money_exact(store: _Store) -> None:
    """A limit of 1010.00 must not come back as 1010.0 or a float, or the policy drifts."""
    with store.unit_of_work.transaction():
        store.mandates.add(samples.mandate())

    latest = store.mandates.latest(samples.BUYER_ID)

    assert latest == samples.mandate()
    assert latest is not None
    assert str(latest.max_auto_order_value) == "1010.00"
    assert str(latest.max_line_value) == "0.10"


def test_mandate_refuses_a_gap_or_an_overwrite(store: _Store) -> None:
    """Old versions stay, so an order can always name the rules it ran under."""
    with store.unit_of_work.transaction():
        store.mandates.add(samples.mandate(version=1))

    with pytest.raises(ValueError, match="version must be 2"), store.unit_of_work.transaction():
        store.mandates.add(samples.mandate(version=1))
    with pytest.raises(ValueError, match="version must be 2"), store.unit_of_work.transaction():
        store.mandates.add(samples.mandate(version=3))

    with store.unit_of_work.transaction():
        store.mandates.add(samples.mandate(version=2))
    latest = store.mandates.latest(samples.BUYER_ID)
    assert latest is not None
    assert latest.version == 2


def test_agent_key_add_replaces_by_hash(store: _Store) -> None:
    """Revoking a key stores it again with a new status; the old status must not win."""
    key = samples.agent_key()
    other_buyer = samples.agent_key(key="key-2", buyer_id="hotel-2")
    with store.unit_of_work.transaction():
        store.agent_keys.add(key)
        store.agent_keys.add(other_buyer)
        store.agent_keys.add(dataclasses.replace(key, status=AgentKeyStatus.REVOKED))

    stored = store.agent_keys.by_hash(key.key_hash)

    assert stored == dataclasses.replace(key, status=AgentKeyStatus.REVOKED)
    assert store.agent_keys.for_buyer(samples.BUYER_ID) == [stored]


def test_user_round_trip(store: _Store) -> None:
    """Approval checks the role, so it must come back as the enum it went in as."""
    user = User(user_id="u_1", buyer_id=None, role=UserRole.STAFF)
    with store.unit_of_work.transaction():
        store.users.add(user)

    assert store.users.get("u_1") == user
    assert store.users.get("u_2") is None


def test_offer_round_trip(store: _Store) -> None:
    """A cart reads its prices from the stored offer, so every nested field must survive."""
    with store.unit_of_work.transaction():
        store.offers.add(samples.offer())

    assert store.offers.get("of_1") == samples.offer()


def test_cart_add_refuses_an_existing_id(store: _Store) -> None:
    """A retried create must not overwrite a cart that is already waiting for approval."""
    with store.unit_of_work.transaction():
        store.carts.add(samples.cart())

    with pytest.raises(ValueError, match="exists"), store.unit_of_work.transaction():
        store.carts.add(samples.cart(state=CartState.AUTO))

    assert store.carts.get("c_1") == samples.cart()


def test_cart_save_needs_a_known_cart(store: _Store) -> None:
    """save moves the state of a stored cart; it must not create one."""
    with pytest.raises(ValueError, match="unknown"), store.unit_of_work.transaction():
        store.carts.save(samples.cart())

    with store.unit_of_work.transaction():
        store.carts.add(samples.cart())
        store.carts.save(samples.cart(state=CartState.ORDERED))

    saved = store.carts.get("c_1")
    assert saved is not None
    assert saved.state is CartState.ORDERED
    assert saved.approve_before.utcoffset() == timedelta(0)
    assert store.carts.for_buyer(samples.BUYER_ID) == [saved]
    assert store.carts.for_buyer("hotel-2") == []


def test_second_order_for_one_cart_is_refused(store: _Store) -> None:
    """Checkout and approve can race on one cart. Only one order may come out."""
    with store.unit_of_work.transaction():
        store.orders.add(samples.order("o_1", "c_1"))

    with pytest.raises(ValueError, match="has an order"), store.unit_of_work.transaction():
        store.orders.add(samples.order("o_2", "c_1"))

    assert store.orders.get("o_1") == samples.order("o_1", "c_1")
    assert store.orders.by_cart("c_1") == samples.order("o_1", "c_1")
    assert store.orders.get("o_2") is None


def test_for_day_finds_orders_with_a_line_on_that_date(store: _Store) -> None:
    """The day limit sums the buyer's orders for one delivery date and no other."""
    later = samples.DELIVERY_DATE + timedelta(days=1)
    with store.unit_of_work.transaction():
        store.orders.add(samples.order("o_1", "c_1"))
        store.orders.add(samples.order("o_2", "c_2", delivery_date=later))

    day_orders = store.orders.for_day(samples.BUYER_ID, samples.DELIVERY_DATE)

    assert [order.order_id for order in day_orders] == ["o_1"]
    assert store.orders.for_day("hotel-2", samples.DELIVERY_DATE) == []


def test_audit_for_cart_keeps_the_insert_order(store: _Store) -> None:
    """The audit trail is read as a story; records with the same time must not swap."""
    with store.unit_of_work.transaction():
        store.audit.append(samples.audit_record("a_2"))
        store.audit.append(samples.audit_record("a_1"))
        store.audit.append(samples.audit_record("a_3", cart_id="c_2"))

    records = store.audit.for_cart("c_1")

    assert records == [samples.audit_record("a_2"), samples.audit_record("a_1")]


def test_used_idempotency_key_is_refused(store: _Store) -> None:
    """Two retries with one key must not both create a cart or an order."""
    record = IdempotencyRecord(
        buyer_id=samples.BUYER_ID,
        key="k_1",
        request_hash="h_1",
        result_id="c_1",
    )
    other_buyer = dataclasses.replace(record, buyer_id="hotel-2")
    with store.unit_of_work.transaction():
        store.idempotency.add(record)
        store.idempotency.add(other_buyer)

    with pytest.raises(ValueError, match="is used"), store.unit_of_work.transaction():
        store.idempotency.add(dataclasses.replace(record, request_hash="h_2"))

    assert store.idempotency.get(samples.BUYER_ID, "k_1") == record
    assert store.idempotency.get(samples.BUYER_ID, "k_2") is None
