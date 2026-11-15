import dataclasses
import threading
from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest

from app.adapters.memory.repositories import (
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryCartRevisionRepository,
    InMemoryIdempotencyRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemoryUnitOfWork,
)
from app.adapters.postgres.database import Database
from app.adapters.postgres.repositories import (
    PostgresAuditRepository,
    PostgresCartRepository,
    PostgresCartRevisionRepository,
    PostgresIdempotencyRepository,
    PostgresMandateRepository,
    PostgresOfferRepository,
    PostgresOrderRepository,
)
from app.adapters.signer import NullSigner
from app.domain.agent_key import User
from app.domain.cart import Cart, CartDraft, CartLineInput, PricedLine
from app.domain.enums import AuditStep, CartState, Decision, FlowPhase, ReasonCode, UserRole
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
)
from app.domain.order import Order
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.mandate_service import MandateService
from app.services.order_service import OrderService
from tests.adapters import samples
from tests.fakes.offer_data import FakeCatalog, FakePriceSource

_MAIN_USER = User(user_id="hotel-1-main", buyer_id=samples.BUYER_ID, role=UserRole.MAIN_USER)
_BEFORE_DEADLINE = samples.NOW - timedelta(hours=1)
_REASON = "Too much milk."


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


class _DenySwitch:
    """A check the test turns on, as a mandate change that forbids the cart would."""

    def __init__(self) -> None:
        self.is_on = False

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        if not self.is_on:
            return []

        return [CheckResult(Decision.DENY, ReasonCode.FORBIDDEN_ALLERGEN, "Forbidden.", None)]


class _World:
    """The service on one store (memory, or Postgres when given), one cart and a clock the test
    can move."""

    def __init__(
        self,
        state: CartState = CartState.PENDING_APPROVAL,
        database: Database | None = None,
    ) -> None:
        self.clock = _Clock(_BEFORE_DEADLINE)
        self.deny = _DenySwitch()
        if database is None:
            self.carts = InMemoryCartRepository()
            revisions = InMemoryCartRevisionRepository()
            self.audit = InMemoryAuditRepository()
            self.orders = InMemoryOrderRepository()
            mandates = InMemoryMandateRepository()
            idempotency = InMemoryIdempotencyRepository()
            offers = InMemoryOfferRepository()
            unit_of_work = InMemoryUnitOfWork()
        else:
            self.carts = PostgresCartRepository(database)
            revisions = PostgresCartRevisionRepository(database)
            self.audit = PostgresAuditRepository(database)
            self.orders = PostgresOrderRepository(database)
            mandates = PostgresMandateRepository(database)
            idempotency = PostgresIdempotencyRepository(database)
            offers = PostgresOfferRepository(database)
            unit_of_work = database
        self.unit_of_work = unit_of_work
        self.cart = samples.cart(state=state)
        with unit_of_work.transaction():
            mandates.add(samples.mandate())
            offers.add(samples.offer())
            self.carts.add(self.cart)
        audit = AuditService(self.audit, self.carts, offers, self.clock, unit_of_work)
        mandate_service = MandateService(mandates, self.clock, audit, unit_of_work)
        self.cart_service = CartService(
            offers,
            self.carts,
            revisions,
            self.orders,
            idempotency,
            mandate_service,
            FakeCatalog(),
            PolicyEngine([OrderLimit(), self.deny]),
            self.clock,
            audit,
            unit_of_work,
        )
        order_service = OrderService(
            self.cart_service,
            self.carts,
            self.orders,
            offers,
            idempotency,
            FakePriceSource(),
            NullSigner(),
            self.clock,
            audit,
            unit_of_work,
        )
        self.order_service = order_service
        self.service = ApprovalService(
            self.carts,
            self.cart_service,
            order_service,
            mandate_service,
            self.clock,
            audit,
            unit_of_work,
        )

    def approve(self, user: User = _MAIN_USER, revision: int = 1) -> Order | Cart:
        return self.service.approve(user, self.cart.cart_id, revision)

    def reject(self, reason: str = _REASON, user: User = _MAIN_USER, revision: int = 1) -> Cart:
        return self.service.reject(user, self.cart.cart_id, revision, reason)

    def steps(self) -> list[AuditStep]:
        return [record.step for record in self.audit.for_cart(self.cart.cart_id)]


def test_reject_ends_the_cart_with_who_when_and_why() -> None:
    """The agent reads the person's reason from the cart and must not send it again."""
    world = _World()

    rejected = world.reject(f"  {_REASON}  ")

    assert rejected.state is CartState.REJECTED
    assert rejected.decided_by == _MAIN_USER.user_id
    assert rejected.decided_at == _BEFORE_DEADLINE
    assert rejected.reject_reason == _REASON
    assert rejected.order_id is None
    assert world.carts.get(world.cart.cart_id) == rejected
    assert rejected == dataclasses.replace(
        world.cart,
        state=CartState.REJECTED,
        decided_by=_MAIN_USER.user_id,
        decided_at=_BEFORE_DEADLINE,
        reject_reason=_REASON,
    )


def test_reject_writes_one_approval_record() -> None:
    """The record must show who said no, and why, next to the agent's own steps."""
    world = _World()

    world.reject()

    [record] = world.audit.for_cart(world.cart.cart_id)
    assert record.step is AuditStep.APPROVAL
    assert record.phase is FlowPhase.APPROVAL
    assert record.actor == _MAIN_USER.user_id
    assert record.input_data == {"reason": _REASON}
    assert record.output_data == {"state": CartState.REJECTED}
    assert record.mandate_version == world.cart.mandate_version
    assert _REASON in record.sentence


@pytest.mark.parametrize(
    "state",
    [
        CartState.AUTO,
        CartState.ORDERED,
        CartState.REJECTED,
        CartState.EXPIRED,
        CartState.DENIED,
    ],
)
def test_only_a_waiting_cart_can_be_rejected(state: CartState) -> None:
    """A decided cart is final, so a late reject must not change it or its record."""
    world = _World(state)

    with pytest.raises(ConflictError):
        world.reject()

    assert world.carts.get(world.cart.cart_id) == world.cart
    assert world.steps() == []


def test_reject_after_the_deadline_keeps_the_expiry() -> None:
    """A dead cart must show EXPIRED everywhere, also after the refused reject."""
    world = _World()
    world.clock.at = world.cart.approve_before

    with pytest.raises(ConflictError):
        world.reject()

    assert world.carts.get(world.cart.cart_id).state is CartState.EXPIRED
    assert world.steps() == [AuditStep.CART]


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_reject_needs_a_reason(reason: str) -> None:
    """The agent tells the buyer why. With no reason there is nothing to tell."""
    world = _World()

    with pytest.raises(InvalidRequestError):
        world.reject(reason)

    assert world.carts.get(world.cart.cart_id) == world.cart
    assert world.steps() == []


def test_other_buyers_cart_is_not_found() -> None:
    """The main user of one buyer must not decide, or learn about, another buyer's cart."""
    world = _World()
    other = dataclasses.replace(_MAIN_USER, user_id="hotel-2-main", buyer_id="hotel-2")

    with pytest.raises(NotFoundError):
        world.reject(user=other)

    assert world.carts.get(world.cart.cart_id) == world.cart


def test_missing_cart_is_not_found() -> None:
    """A made up cart id gets the same answer as another buyer's cart, so ids leak nothing."""
    world = _World()

    with pytest.raises(NotFoundError):
        world.service.reject(_MAIN_USER, "c_missing", 1, _REASON)


def test_user_with_no_buyer_is_refused() -> None:
    """Staff act for no buyer, so they must not decide any buyer's cart."""
    world = _World()
    staff = dataclasses.replace(_MAIN_USER, user_id="staff-1", buyer_id=None)

    with pytest.raises(ForbiddenError):
        world.reject(user=staff)

    assert world.carts.get(world.cart.cart_id) == world.cart
    assert world.steps() == []


def test_approve_places_the_order_in_the_approvers_name() -> None:
    """The person's yes is what allows a cart over the limit, so the order and cart say who."""
    world = _World()

    order = world.approve()

    assert isinstance(order, Order)
    assert order.approved_by == _MAIN_USER.user_id
    assert world.orders.by_cart(world.cart.cart_id) == order
    stored = world.carts.get(world.cart.cart_id)
    assert stored.state is CartState.ORDERED
    assert stored.order_id == order.order_id
    assert stored.decided_by == _MAIN_USER.user_id
    assert stored.decided_at == _BEFORE_DEADLINE


def test_approve_records_the_person_before_the_order() -> None:
    """The timeline must show who approved, next to the policy rerun and the order."""
    world = _World()

    order = world.approve()

    approval, policy, placed = world.audit.for_cart(world.cart.cart_id)
    assert [approval.step, policy.step, placed.step] == [
        AuditStep.APPROVAL,
        AuditStep.POLICY,
        AuditStep.ORDER,
    ]
    assert approval.phase is FlowPhase.APPROVAL
    assert approval.actor == _MAIN_USER.user_id
    assert approval.output_data == {"order_id": order.order_id}
    assert placed.actor == _MAIN_USER.user_id


def test_second_approve_returns_the_same_order() -> None:
    """A double tap on the phone must not place a second order or a second audit trail."""
    world = _World()
    first = world.approve()
    steps = world.steps()

    second = world.approve()

    assert second == first
    assert world.steps() == steps


def test_approve_that_waited_on_the_lock_returns_the_first_order(monkeypatch) -> None:
    """Two taps at once: the second finds the cart ORDERED under the lock and must not 409."""
    world = _World()
    real_get_cart = world.cart_service.get_cart
    first = []

    def first_tap_commits_now(buyer_id: str, cart_id: str) -> Cart:
        cart = real_get_cart(buyer_id, cart_id)
        monkeypatch.setattr(world.cart_service, "get_cart", real_get_cart)
        first.append(world.approve())
        return cart

    monkeypatch.setattr(world.cart_service, "get_cart", first_tap_commits_now)

    second = world.approve()

    assert isinstance(second, Order)
    assert second == first[0]


@pytest.mark.parametrize("state", [CartState.AUTO, CartState.REJECTED])
def test_cart_that_waits_for_nobody_cannot_be_approved(state: CartState) -> None:
    """An AUTO cart is the agent's to check out, and a rejected cart is final."""
    world = _World(state)

    with pytest.raises(ConflictError, match="cannot be approved"):
        world.approve()

    assert world.carts.get(world.cart.cart_id) == world.cart
    assert world.orders.by_cart(world.cart.cart_id) is None
    assert world.steps() == []


@pytest.mark.parametrize("state", [CartState.EXPIRED, CartState.DENIED])
def test_ended_cart_is_returned_with_its_reason(state: CartState) -> None:
    """The door turns the cart into a 409 whose text is the reason the cart ended."""
    world = _World(state)

    result = world.approve()

    assert result == world.cart
    assert world.orders.by_cart(world.cart.cart_id) is None
    assert world.steps() == []


def test_approve_after_the_deadline_expires_the_cart() -> None:
    """No order can reach Valio Aimo after closing time, also with a person's yes."""
    world = _World()
    world.clock.at = world.cart.approve_before

    result = world.approve()

    assert result.state is CartState.EXPIRED
    assert world.carts.get(world.cart.cart_id).state is CartState.EXPIRED
    assert world.orders.by_cart(world.cart.cart_id) is None


def test_approve_under_a_mandate_that_now_forbids_the_cart_denies_it() -> None:
    """A person's yes cannot override a rule: DENY holds over approval."""
    world = _World()
    world.deny.is_on = True

    result = world.approve()

    assert result.state is CartState.DENIED
    assert world.carts.get(world.cart.cart_id).state is CartState.DENIED
    assert world.orders.by_cart(world.cart.cart_id) is None


def test_denied_approve_records_the_person() -> None:
    """The timeline must show that a person said yes and the mandate still said no."""
    world = _World()
    world.deny.is_on = True

    world.approve()

    approval, policy = world.audit.for_cart(world.cart.cart_id)
    assert [approval.step, policy.step] == [AuditStep.APPROVAL, AuditStep.POLICY]
    assert approval.actor == _MAIN_USER.user_id
    assert "order_id" not in approval.output_data
    assert policy.decision is Decision.DENY


def test_approve_after_a_price_change_records_the_person() -> None:
    """The timeline must show that a person said yes before the changed price ended the cart."""
    world = _World()
    # The offer snapshot ran out, so the order path reads price and stock again. The fake has
    # no price, so the line no longer holds.
    world.carts.save(dataclasses.replace(world.cart, valid_until=_BEFORE_DEADLINE))

    result = world.approve()

    assert result.reason_codes == (ReasonCode.PRICE_OR_STOCK_CHANGED,)
    approval, expiry = world.audit.for_cart(world.cart.cart_id)
    assert [approval.step, expiry.step] == [AuditStep.APPROVAL, AuditStep.CART]
    assert approval.actor == _MAIN_USER.user_id


def test_approve_of_other_buyers_cart_is_not_found() -> None:
    """The main user of one buyer must not order, or learn about, another buyer's cart."""
    world = _World()
    other = dataclasses.replace(_MAIN_USER, user_id="hotel-2-main", buyer_id="hotel-2")

    with pytest.raises(NotFoundError):
        world.approve(other)

    assert world.orders.by_cart(world.cart.cart_id) is None


def test_approve_by_a_user_with_no_buyer_is_refused() -> None:
    """Staff act for no buyer, so they must not order for any buyer."""
    world = _World()
    staff = dataclasses.replace(_MAIN_USER, user_id="staff-1", buyer_id=None)

    with pytest.raises(ForbiddenError):
        world.approve(staff)

    assert world.orders.by_cart(world.cart.cart_id) is None


def test_postgres_racing_approves_give_one_order(database: Database) -> None:
    """Two taps at the same time: the cart lock lets one place the order, the other reads it."""
    world = _World(database=database)
    barrier = threading.Barrier(2)
    results: list[Order | Cart | Exception] = []

    def tap() -> None:
        barrier.wait()
        try:
            results.append(world.approve())
        # Kept, not raised: an error in a thread would not fail the test.
        except Exception as error:
            results.append(error)

    threads = [threading.Thread(target=tap) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    first, second = results
    assert isinstance(first, Order)
    assert second == first
    assert world.steps().count(AuditStep.ORDER) == 1


def _revise(world: _World) -> Cart:
    line = CartLineInput(offer_id="of_1", product_id="p_2", qty=3)
    draft = CartDraft(lines=(line,), request_text="make it 3", clarifications=())
    return world.cart_service.revise_cart(samples.agent_key(), world.cart.cart_id, 1, draft, "k-r1")


def test_withdrawn_cart_cannot_be_approved() -> None:
    """The buyer said "forget it", so a person's yes must not order it any more."""
    world = _World()
    world.cart_service.withdraw_cart(samples.agent_key(), world.cart.cart_id)

    with pytest.raises(ConflictError, match=CartState.WITHDRAWN):
        world.approve()

    assert world.orders.by_cart(world.cart.cart_id) is None


def _approve_while_the_agent_revises(world: _World, monkeypatch) -> Order | Cart:
    real_get_cart = world.cart_service.get_cart

    def agent_revises_after_the_read(buyer_id: str, cart_id: str) -> Cart:
        cart = real_get_cart(buyer_id, cart_id)
        _revise(world)
        return cart

    monkeypatch.setattr(world.cart_service, "get_cart", agent_revises_after_the_read)
    return world.approve()


def test_approve_of_a_revision_the_main_user_did_not_see_is_refused(monkeypatch) -> None:
    """The main user said yes to the lines they saw. A newer revision needs its own yes."""
    world = _World()

    with pytest.raises(ConflictError) as error:
        _approve_while_the_agent_revises(world, monkeypatch)

    assert "revision 2" in error.value.message
    assert world.orders.by_cart(world.cart.cart_id) is None
    assert world.carts.get(world.cart.cart_id).revision == 2


def test_postgres_approve_of_an_unseen_revision_is_refused(database: Database, monkeypatch) -> None:
    """The revision number must survive the store, or the guard would pass a stale yes."""
    world = _World(database=database)

    with pytest.raises(ConflictError):
        _approve_while_the_agent_revises(world, monkeypatch)

    assert world.orders.by_cart(world.cart.cart_id) is None
    assert world.carts.get(world.cart.cart_id).revision == 2


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_postgres_stale_revision_does_not_decide_cart(database, action):
    world = _World(database=database)
    revised = dataclasses.replace(world.cart, revision=2)
    with world.unit_of_work.transaction():
        world.carts.save(revised)

    with pytest.raises(ConflictError, match="revision 2"):
        getattr(world, action)(revision=1)

    assert world.carts.get(world.cart.cart_id) == revised
    assert world.orders.by_cart(world.cart.cart_id) is None
    assert world.steps() == []


def test_approval_does_not_return_order_for_a_concurrent_new_revision(monkeypatch):
    """A newer revision can be ordered before the old approval obtains the cart lock."""
    world = _World()
    real_get_cart = world.cart_service.get_cart

    def revise_and_order(buyer_id, cart_id):
        before = real_get_cart(buyer_id, cart_id)
        revised = _revise(world)
        world.order_service.place(revised, _MAIN_USER)
        return before

    monkeypatch.setattr(world.cart_service, "get_cart", revise_and_order)

    with pytest.raises(ConflictError, match="revision 2"):
        world.approve(revision=1)

    assert world.orders.by_cart(world.cart.cart_id).revision == 2
    assert world.steps().count(AuditStep.ORDER) == 1
