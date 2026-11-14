"""One behaviour, two adapters: each test runs on the memory and on the Postgres store."""

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.memory.repositories import (
    InMemoryAgentKeyRepository,
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryCartRevisionRepository,
    InMemoryIdempotencyRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemorySessionRepository,
    InMemoryUnitOfWork,
    InMemoryUserRepository,
)
from app.adapters.postgres.repositories import (
    PostgresAgentKeyRepository,
    PostgresAuditRepository,
    PostgresCartRepository,
    PostgresCartRevisionRepository,
    PostgresIdempotencyRepository,
    PostgresMandateRepository,
    PostgresOfferRepository,
    PostgresOrderRepository,
    PostgresSessionRepository,
    PostgresUserRepository,
)
from app.domain.agent_key import User
from app.domain.cart import CartRevision
from app.domain.enums import AgentKeyStatus, CartState, RevisionAuthor, UserRole
from app.domain.idempotency import IdempotencyRecord
from app.domain.session import Session
from app.services.ports.repositories import (
    AgentKeyRepository,
    AuditRepository,
    CartRepository,
    CartRevisionRepository,
    IdempotencyRepository,
    MandateRepository,
    OfferRepository,
    OrderRepository,
    SessionRepository,
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
    revisions: CartRevisionRepository
    orders: OrderRepository
    audit: AuditRepository
    idempotency: IdempotencyRepository
    sessions: SessionRepository
    unit_of_work: UnitOfWork


def _memory_store() -> _Store:
    return _Store(
        mandates=InMemoryMandateRepository(),
        agent_keys=InMemoryAgentKeyRepository(),
        users=InMemoryUserRepository(),
        offers=InMemoryOfferRepository(),
        carts=InMemoryCartRepository(),
        revisions=InMemoryCartRevisionRepository(),
        orders=InMemoryOrderRepository(),
        audit=InMemoryAuditRepository(),
        idempotency=InMemoryIdempotencyRepository(),
        sessions=InMemorySessionRepository(),
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
        revisions=PostgresCartRevisionRepository(database),
        orders=PostgresOrderRepository(database),
        audit=PostgresAuditRepository(database),
        idempotency=PostgresIdempotencyRepository(database),
        sessions=PostgresSessionRepository(database),
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


def test_mark_used_keeps_a_revoke_made_after_the_read(store: _Store) -> None:
    """A call read the key as active, then the main user revoked it. The call must not undo that."""
    revoked = dataclasses.replace(
        samples.agent_key(),
        status=AgentKeyStatus.REVOKED,
        last_used_at=None,
    )
    with store.unit_of_work.transaction():
        store.agent_keys.add(revoked)

    with store.unit_of_work.transaction():
        store.agent_keys.mark_used(revoked.key_hash, samples.NOW, samples.NOW)

    assert store.agent_keys.by_hash(revoked.key_hash) == dataclasses.replace(
        revoked,
        last_used_at=samples.NOW,
    )


@pytest.mark.parametrize(
    ("cutoff", "expected"),
    [
        (samples.NOW - timedelta(seconds=1), samples.NOW),
        (samples.NOW, samples.NOW + timedelta(minutes=1)),
    ],
    ids=["used-after-cutoff", "used-at-cutoff"],
)
def test_mark_used_writes_only_when_the_last_use_is_old(
    store: _Store,
    cutoff: datetime,
    expected: datetime,
) -> None:
    """Two calls that read the same old time must not both write. The second sees the new time."""
    key = samples.agent_key()
    with store.unit_of_work.transaction():
        store.agent_keys.add(key)

    with store.unit_of_work.transaction():
        store.agent_keys.mark_used(key.key_hash, samples.NOW + timedelta(minutes=1), cutoff)

    stored = store.agent_keys.by_hash(key.key_hash)
    assert stored is not None
    assert stored.last_used_at == expected


def test_agent_key_revoke_reports_only_the_first_change(store: _Store) -> None:
    """Two revokes must write one record, so only the one that changed the key may say so."""
    key = samples.agent_key()
    with store.unit_of_work.transaction():
        store.agent_keys.add(key)
        first = store.agent_keys.revoke(key.key_hash)
        second = store.agent_keys.revoke(key.key_hash)
        unknown = store.agent_keys.revoke("no-such-hash")

    assert (first, second, unknown) == (True, False, False)
    assert store.agent_keys.by_hash(key.key_hash) == dataclasses.replace(
        key,
        status=AgentKeyStatus.REVOKED,
    )


def test_user_round_trip(store: _Store) -> None:
    """Approval checks the role, so it must come back as the enum it went in as."""
    user = User(user_id="u_1", buyer_id=None, role=UserRole.STAFF)
    with store.unit_of_work.transaction():
        store.users.add(user)

    assert store.users.get("u_1") == user
    assert store.users.get("u_2") is None


def test_session_remove_and_expiry(store: _Store) -> None:
    """Logout and the prune must remove only their own sessions, so others stay logged in."""
    now = datetime(2026, 11, 14, 12, tzinfo=UTC)
    live = Session("h_live", "u_1", now + timedelta(hours=1), "t_1")
    expired = Session("h_expired", "u_1", now, "t_1")
    logged_out = Session("h_out", "u_1", now + timedelta(hours=1), "t_1")
    with store.unit_of_work.transaction():
        store.sessions.add(live)
        store.sessions.add(expired)
        store.sessions.add(logged_out)

    with store.unit_of_work.transaction():
        store.sessions.remove("h_out")
        store.sessions.remove("h_unknown")
        store.sessions.remove_expired(now)

    assert store.sessions.get("h_live") == live
    assert store.sessions.get("h_expired") is None
    assert store.sessions.get("h_out") is None


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


def test_get_locked_reads_the_cart_in_a_transaction(store: _Store) -> None:
    """Expiry reads the cart again under the lock, so it must see the stored state."""
    with store.unit_of_work.transaction():
        store.carts.add(samples.cart())

    with store.unit_of_work.transaction():
        assert store.carts.get_locked("c_1") == samples.cart()
        assert store.carts.get_locked("c_missing") is None


def _revision(revision: int, author: RevisionAuthor) -> CartRevision:
    cart = dataclasses.replace(samples.cart(), revision=revision)
    return CartRevision(cart=cart, author=author, created_at=samples.NOW)


def test_cart_revisions_are_kept_in_order_and_never_replaced(store: _Store) -> None:
    """The main user compares what they approve with what the agent first asked for."""
    second = _revision(2, RevisionAuthor.MAIN_USER)
    first = _revision(1, RevisionAuthor.AGENT)
    with store.unit_of_work.transaction():
        store.revisions.add(second)
        store.revisions.add(first)

    with pytest.raises(ValueError, match="exists"), store.unit_of_work.transaction():
        store.revisions.add(_revision(1, RevisionAuthor.MAIN_USER))

    assert store.revisions.for_cart("c_1") == [first, second]
    assert store.revisions.for_cart("c_missing") == []


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


def test_audit_for_cart_adds_the_records_of_its_requests(store: _Store) -> None:
    """Search and offer records have no cart yet, so the request id joins them to it."""
    search = samples.audit_record("a_1", cart_id=None, request_id="r_1")
    other = samples.audit_record("a_2", cart_id=None, request_id="r_2")
    intruder = samples.audit_record("a_3", cart_id=None, request_id="r_1", buyer_id="hotel-2")
    unowned = samples.audit_record("a_4", cart_id=None, request_id="r_1", buyer_id=None)
    cart = samples.audit_record("a_5", request_id=None)
    with store.unit_of_work.transaction():
        for record in (search, other, intruder, unowned, cart):
            store.audit.append(record)

    linked = store.audit.for_cart("c_1", buyer_id=samples.BUYER_ID, request_ids=["r_1"])
    no_buyer = store.audit.for_cart("c_1", request_ids=["r_1"])

    assert linked == [search, cart]
    # Without a buyer, a record with no buyer must not count as a match.
    assert no_buyer == [cart]


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


def test_confirmed_history_is_scoped_to_buyer_and_excludes_auto(store: _Store) -> None:
    """All human confirmations count, even old ones; no other buyer or AUTO order counts."""
    confirmed = dataclasses.replace(
        samples.order("confirmed", "c_confirmed"), placed_at=samples.NOW - timedelta(days=1000)
    )
    automatic = dataclasses.replace(samples.order("automatic", "c_auto"), approved_by=None)
    other = dataclasses.replace(samples.order("other", "c_other"), buyer_id="buyer-b")
    with store.unit_of_work.transaction():
        for order in (confirmed, automatic, other):
            store.orders.add(order)

    assert store.orders.list_confirmed(samples.BUYER_ID) == [confirmed]
    assert store.orders.list_confirmed("buyer-b") == [other]
    assert store.orders.list_confirmed("new-buyer") == []
