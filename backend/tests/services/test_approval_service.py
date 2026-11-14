import dataclasses
from datetime import datetime, timedelta

import pytest

from app.adapters.memory.repositories import (
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryIdempotencyRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemoryUnitOfWork,
)
from app.adapters.signer import NullSigner
from app.domain.agent_key import User
from app.domain.cart import Cart
from app.domain.enums import AuditStep, CartState, FlowPhase, UserRole
from app.domain.errors import (
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
)
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.mandate_service import MandateService
from app.services.order_service import OrderService
from tests.adapters import samples
from tests.fakes.offer_data import FakePriceSource

_MAIN_USER = User(user_id="hotel-1-main", buyer_id=samples.BUYER_ID, role=UserRole.MAIN_USER)
_BEFORE_DEADLINE = samples.NOW - timedelta(hours=1)
_REASON = "Too much milk."


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


class _World:
    """The service on in-memory stores, with one cart and a clock the test can move."""

    def __init__(self, state: CartState = CartState.PENDING_APPROVAL) -> None:
        self.clock = _Clock(_BEFORE_DEADLINE)
        self.carts = InMemoryCartRepository()
        self.audit = InMemoryAuditRepository()
        self.cart = samples.cart(state=state)
        self.carts.add(self.cart)
        mandates = InMemoryMandateRepository()
        mandates.add(samples.mandate())
        orders = InMemoryOrderRepository()
        idempotency = InMemoryIdempotencyRepository()
        offers = InMemoryOfferRepository()
        unit_of_work = InMemoryUnitOfWork()
        audit = AuditService(self.audit, self.clock, unit_of_work)
        mandate_service = MandateService(mandates, self.clock, audit, unit_of_work)
        cart_service = CartService(
            offers,
            self.carts,
            orders,
            idempotency,
            mandate_service,
            PolicyEngine([OrderLimit()]),
            self.clock,
            audit,
            unit_of_work,
        )
        order_service = OrderService(
            cart_service,
            self.carts,
            orders,
            offers,
            idempotency,
            FakePriceSource(),
            NullSigner(),
            self.clock,
            audit,
            unit_of_work,
        )
        self.service = ApprovalService(
            self.carts,
            cart_service,
            order_service,
            mandate_service,
            self.clock,
            audit,
            unit_of_work,
        )

    def reject(self, reason: str = _REASON, user: User = _MAIN_USER) -> Cart:
        return self.service.reject(user, self.cart.cart_id, reason)

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
        world.service.reject(_MAIN_USER, "c_missing", _REASON)


def test_user_with_no_buyer_is_refused() -> None:
    """Staff act for no buyer, so they must not decide any buyer's cart."""
    world = _World()
    staff = dataclasses.replace(_MAIN_USER, user_id="staff-1", buyer_id=None)

    with pytest.raises(ForbiddenError):
        world.reject(user=staff)

    assert world.carts.get(world.cart.cart_id) == world.cart
    assert world.steps() == []
