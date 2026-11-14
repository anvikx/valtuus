import contextlib
import dataclasses
import threading
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

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
from app.domain.agent_key import User
from app.domain.cart import Cart, CartDraft, CartLineInput, PricedLine
from app.domain.enums import (
    AuditStep,
    CartState,
    Decision,
    FlowPhase,
    ReasonCode,
    StockModel,
    UserRole,
)
from app.domain.errors import ConflictError, NotFoundError, UpstreamUnavailableError
from app.domain.mandate import Mandate
from app.domain.offer import Offer, OfferLine
from app.domain.order import Order
from app.domain.policy.auto_order_switch import AutoOrderSwitch
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.daily_limit import DailyLimit
from app.domain.policy.duplicate_order import DuplicateOrder
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from app.domain.policy.previously_rejected import PreviouslyRejected
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.mandate_service import MandateService
from app.services.offer_service import ISSUER
from app.services.order_service import OrderService
from tests.adapters import samples
from tests.fakes.offer_data import (
    CLOSING,
    MILK_ID,
    MONDAY,
    NOW,
    FakeCatalog,
    FakePriceSource,
    price,
    stock,
)

_LIMIT = Decimal("500.00")
_RAISED = Decimal("1500.00")
_GTIN = "6408430000012"
_SIGNATURE = "header.payload.signature"
_STALE = NOW + timedelta(minutes=20)
_RENDEZVOUS_SECONDS = 0.5


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


class _RecordingSigner:
    def __init__(self) -> None:
        self.payloads = []

    def sign(self, payload):
        self.payloads.append(payload)
        return _SIGNATURE


class _DenySwitch:
    """A check the test turns on, as a mandate change that forbids the cart would."""

    def __init__(self) -> None:
        self.is_on = False

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        if not self.is_on:
            return []

        return [CheckResult(Decision.DENY, ReasonCode.FORBIDDEN_ALLERGEN, "Forbidden.", None)]


class _Rendezvous:
    """Holds each policy run until the other racer also read the day's orders, or a timeout.

    Without it the first checkout often commits before the second one reads, and a race test
    would pass with no day lock at all.
    """

    def __init__(self) -> None:
        self.barrier: threading.Barrier | None = None

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        if self.barrier is None:
            return []

        # With the day lock the second racer waits on the lock, not here, so this times out.
        with contextlib.suppress(threading.BrokenBarrierError):
            self.barrier.wait(timeout=_RENDEZVOUS_SECONDS)
        return []


class _World:
    """Cart and order services on one store (memory, or Postgres when given) and one clock."""

    def __init__(
        self,
        source: FakePriceSource | None = None,
        database: Database | None = None,
    ) -> None:
        self.clock = _Clock(NOW)
        self.source = source or FakePriceSource([price()], [stock()])
        self.signer = _RecordingSigner()
        self.deny = _DenySwitch()
        self.rendezvous = _Rendezvous()
        if database is None:
            self.offers = InMemoryOfferRepository()
            self.carts = InMemoryCartRepository()
            revisions = InMemoryCartRevisionRepository()
            self.orders = InMemoryOrderRepository()
            self.mandates = InMemoryMandateRepository()
            self.audit = InMemoryAuditRepository()
            self.idempotency = InMemoryIdempotencyRepository()
            self.unit_of_work = InMemoryUnitOfWork()
        else:
            self.offers = PostgresOfferRepository(database)
            self.carts = PostgresCartRepository(database)
            revisions = PostgresCartRevisionRepository(database)
            self.orders = PostgresOrderRepository(database)
            self.mandates = PostgresMandateRepository(database)
            self.audit = PostgresAuditRepository(database)
            self.idempotency = PostgresIdempotencyRepository(database)
            self.unit_of_work = database
        unit_of_work = self.unit_of_work
        audit = AuditService(self.audit, self.carts, self.offers, self.clock, unit_of_work)
        with unit_of_work.transaction():
            self.mandates.add(_mandate(1, _LIMIT))
            self.offers.add(_offer())
        self.cart_service = CartService(
            self.offers,
            self.carts,
            revisions,
            self.orders,
            self.idempotency,
            MandateService(self.mandates, self.clock, audit, unit_of_work),
            FakeCatalog(),
            PolicyEngine(
                [
                    AutoOrderSwitch(),
                    OrderLimit(),
                    DailyLimit(),
                    DuplicateOrder(),
                    PreviouslyRejected(),
                    self.deny,
                    self.rendezvous,
                ]
            ),
            self.clock,
            audit,
            unit_of_work,
        )
        self.service = OrderService(
            self.cart_service,
            self.carts,
            self.orders,
            self.offers,
            self.idempotency,
            self.source,
            self.signer,
            self.clock,
            audit,
            unit_of_work,
        )

    def cart(self, qty: int, key: str | None = None):
        draft = CartDraft(
            lines=(CartLineInput(offer_id="o_1", product_id=MILK_ID, qty=qty),),
            request_text="milk for Monday",
            clarifications=(),
        )
        return self.cart_service.create_cart(samples.agent_key(), draft, key or f"cart-{qty}")

    def checkout(self, cart_id: str, key: str = "k-1", buyer: str = samples.BUYER_ID):
        return self.service.checkout(samples.agent_key(buyer_id=buyer), cart_id, key)

    def raise_limit(self, version: int, limit: Decimal) -> None:
        with self.unit_of_work.transaction():
            self.mandates.add(_mandate(version, limit))

    def steps(self, cart_id: str) -> list[AuditStep]:
        return [record.step for record in self.audit.for_cart(cart_id)]


def _mandate(version: int, limit: Decimal) -> Mandate:
    return dataclasses.replace(
        samples.mandate(version),
        max_auto_order_value=limit,
        max_auto_value_per_delivery_date=limit,
    )


def _offer() -> Offer:
    line: OfferLine = dataclasses.replace(
        samples.offer().lines[0],
        product_id=MILK_ID,
        gtin=_GTIN,
        name=f"Milk {MILK_ID}",
        unit_price=Decimal("1.01"),
        price_valid_to=MONDAY + timedelta(days=30),
        available_date=MONDAY,
        closing_time=CLOSING,
        substitute_for=None,
    )
    return dataclasses.replace(
        samples.offer("o_1"),
        buyer_id=samples.BUYER_ID,
        issued_at=NOW,
        valid_until=NOW + timedelta(minutes=15),
        lines=(line,),
    )


def test_auto_cart_is_ordered_at_the_stored_offer_price() -> None:
    """The order uses the price the gateway stored, and records who placed it and why."""
    world = _World()
    cart = world.cart(100)

    order = world.checkout(cart.cart_id)

    assert isinstance(order, Order)
    (line,) = order.lines
    assert line.gtin == _GTIN
    assert line.unit_price == Decimal("1.01")
    assert line.line_total == Decimal("101.00")
    assert line.delivery_date == MONDAY
    assert order.total_ex_vat == Decimal("101.00")
    assert order.buyer_id == samples.BUYER_ID
    assert order.placed_at == NOW
    assert order.placed_by == "Claude Code (agent)"
    assert order.approved_by is None
    assert order.offer_ids == ("o_1",)
    assert order.mandate_version == 1
    assert order.issuer == ISSUER
    assert world.orders.by_cart(cart.cart_id) == order
    stored = world.carts.get(cart.cart_id)
    assert stored.state is CartState.ORDERED
    assert stored.order_id == order.order_id
    assert world.steps(cart.cart_id)[-2:] == [AuditStep.POLICY, AuditStep.ORDER]


def test_order_names_the_cart_revision_it_was_placed_from() -> None:
    """The confirmation must show which version of a changed cart was ordered."""
    world = _World()
    cart = dataclasses.replace(world.cart(100), revision=2)
    with world.unit_of_work.transaction():
        world.carts.save(cart)

    order = world.checkout(cart.cart_id)

    assert order.revision == 2


def test_confirmation_is_signed_without_its_signature_field() -> None:
    """The agent checks the signature on the body it got, which has buyer_id but no signature."""
    world = _World()
    cart = world.cart(100)

    order = world.checkout(cart.cart_id)

    assert order.signature == _SIGNATURE
    (payload,) = world.signer.payloads
    assert "signature" not in payload
    assert payload["order_id"] == order.order_id
    assert payload["buyer_id"] == samples.BUYER_ID


def test_pending_cart_is_ordered_after_the_limit_is_raised() -> None:
    """A raised limit lets the agent place the waiting cart, under the new mandate version."""
    world = _World()
    cart = world.cart(1000)
    world.raise_limit(2, _RAISED)

    order = world.checkout(cart.cart_id)

    assert isinstance(order, Order)
    assert order.mandate_version == 2
    (*_, policy_record, _order_record) = world.audit.for_cart(cart.cart_id)
    assert policy_record.decision is Decision.AUTO
    assert policy_record.mandate_version == 2


def test_auto_cart_over_a_lowered_limit_waits_and_the_change_is_kept() -> None:
    """The 409 is built from a committed state, so get_cart and the audit show it too."""
    world = _World()
    cart = world.cart(100)
    world.raise_limit(2, Decimal("50.00"))

    result = world.checkout(cart.cart_id)

    assert result.state is CartState.PENDING_APPROVAL
    assert result.decision is Decision.HUMAN
    # raise_limit sets both limits, so both reasons show.
    assert result.reason_codes == (ReasonCode.OVER_AUTO_LIMIT, ReasonCode.OVER_DAILY_AUTO_LIMIT)
    assert result.mandate_version == 2
    assert world.cart_service.get_cart(samples.BUYER_ID, cart.cart_id).state is (
        CartState.PENDING_APPROVAL
    )
    assert world.steps(cart.cart_id)[-1] is AuditStep.POLICY
    assert world.orders.by_cart(cart.cart_id) is None


def test_checkout_after_the_same_order_names_the_earlier_order() -> None:
    """Two equal carts were AUTO when made. The second must wait and show which order it repeats."""
    world = _World()
    first = world.cart(100)
    second = world.cart(100, key="cart-2")
    earlier = world.checkout(first.cart_id)

    result = world.checkout(second.cart_id, key="k-2")

    assert result.state is CartState.PENDING_APPROVAL
    assert result.reason_codes == (ReasonCode.DUPLICATE_ORDER,)
    assert result.duplicate_of_order_id == earlier.order_id


def test_checkout_after_a_reject_of_the_same_cart_is_denied_with_the_reason() -> None:
    """A twin made before the person said no must not slip through at checkout."""
    world = _World()
    first = world.cart(100)
    second = world.cart(100, key="cart-2")
    rejected = dataclasses.replace(
        first,
        state=CartState.REJECTED,
        decided_at=NOW,
        reject_reason="We have milk",
    )
    with world.unit_of_work.transaction():
        world.carts.save(rejected)

    result = world.checkout(second.cart_id)

    assert result.state is CartState.DENIED
    assert result.reason_codes == (ReasonCode.PREVIOUSLY_REJECTED,)
    assert result.previous_reject_reason == "We have milk"


def test_auto_cart_waits_after_automatic_orders_are_turned_off() -> None:
    """The main user turns the switch off to stop the agent. A cart made before must stop too."""
    world = _World()
    cart = world.cart(100)
    switched_off = dataclasses.replace(world.mandates.latest(samples.BUYER_ID), version=2)
    with world.unit_of_work.transaction():
        world.mandates.add(dataclasses.replace(switched_off, can_auto_order=False))

    result = world.checkout(cart.cart_id)

    assert result.state is CartState.PENDING_APPROVAL
    assert result.reason_codes == (ReasonCode.AUTO_ORDERS_OFF,)
    assert world.orders.by_cart(cart.cart_id) is None


def test_pending_cart_still_over_the_limit_stays_pending() -> None:
    """Checkout cannot get around the person: the refusal is recorded and nothing is ordered."""
    world = _World()
    cart = world.cart(1000)

    result = world.checkout(cart.cart_id)

    assert result.state is CartState.PENDING_APPROVAL
    assert world.steps(cart.cart_id) == [AuditStep.CART, AuditStep.POLICY, AuditStep.POLICY]
    assert world.orders.by_cart(cart.cart_id) is None


def test_denied_by_the_current_mandate_ends_the_cart() -> None:
    """A rule added after the cart was made still holds at checkout."""
    world = _World()
    cart = world.cart(100)
    world.deny.is_on = True

    result = world.checkout(cart.cart_id)

    assert result.state is CartState.DENIED
    assert result.reason_codes == (ReasonCode.FORBIDDEN_ALLERGEN,)
    assert world.carts.get(cart.cart_id).state is CartState.DENIED


def test_checkout_after_the_deadline_expires_the_cart() -> None:
    """No order can reach Valio Aimo after closing time, so the agent must get new offers."""
    world = _World()
    cart = world.cart(100)
    world.clock.at = CLOSING

    result = world.checkout(cart.cart_id)

    assert result.state is CartState.EXPIRED
    assert result.reason_codes == (ReasonCode.CUTOFF_PASSED,)
    assert world.orders.by_cart(cart.cart_id) is None


def test_fresh_offer_is_ordered_without_a_valio_call() -> None:
    """Inside the 15 minutes the stored stock snapshot is still good."""
    world = _World()
    cart = world.cart(100)

    world.checkout(cart.cart_id)

    assert world.source.calls == []


def test_stale_offer_with_the_same_price_and_stock_is_ordered() -> None:
    """After the snapshot runs out the gateway reads again, and an unchanged offer still holds."""
    world = _World(FakePriceSource([price()], [stock(amount=100)]))
    cart = world.cart(100)
    world.clock.at = _STALE

    order = world.checkout(cart.cart_id)

    assert isinstance(order, Order)
    assert [route for route, _ids, day in world.source.calls if day == MONDAY] == [
        "prices",
        "availability",
    ]


@pytest.mark.parametrize(
    "source",
    [
        FakePriceSource([price(unit_price="1.10")], [stock()]),
        FakePriceSource([price()], [stock(amount=99)]),
        FakePriceSource([], [stock()]),
        FakePriceSource([price()], []),
        FakePriceSource([price()], [stock(available_date=MONDAY + timedelta(days=1))]),
        FakePriceSource([price(valid_to=MONDAY - timedelta(days=1))], [stock()]),
    ],
    ids=["price", "stock", "no-price", "no-stock", "later-date", "price-ends"],
)
def test_stale_offer_that_changed_expires_the_cart(source: FakePriceSource) -> None:
    """The buyer agreed to that price and date. Another one needs a new offer and a new cart."""
    world = _World(source)
    cart = world.cart(100)
    world.clock.at = _STALE

    result = world.checkout(cart.cart_id)

    assert result.state is CartState.EXPIRED
    assert result.reason_codes == (ReasonCode.PRICE_OR_STOCK_CHANGED,)
    assert "new offers" in result.reason_sentences[0]
    assert world.carts.get(cart.cart_id).state is CartState.EXPIRED
    assert world.orders.by_cart(cart.cart_id) is None


def test_unconfirmed_stock_is_judged_as_at_offer_time() -> None:
    """Terminal stock had no count when the cart was made either, so no count is not a change."""
    world = _World(FakePriceSource([price()], [stock(amount=1, model=StockModel.TERMINAL)]))
    cart = world.cart(100)
    world.clock.at = _STALE

    assert isinstance(world.checkout(cart.cart_id), Order)


def test_valio_failure_changes_nothing() -> None:
    """A technical error is never a decision: the cart stays open for a retry."""
    failure = UpstreamUnavailableError("Valio Aimo is down.", "Try again.")
    world = _World(FakePriceSource(error=failure))
    cart = world.cart(100)
    world.clock.at = _STALE

    with pytest.raises(UpstreamUnavailableError):
        world.checkout(cart.cart_id)

    assert world.carts.get(cart.cart_id).state is CartState.AUTO


def test_retry_with_the_same_key_returns_the_first_order() -> None:
    """A lost answer must not place a second order or a second audit trail."""
    world = _World()
    cart = world.cart(100)

    first = world.checkout(cart.cart_id)
    steps = world.steps(cart.cart_id)
    second = world.checkout(cart.cart_id)

    assert second == first
    assert world.steps(cart.cart_id) == steps


def test_parallel_retry_with_the_same_key_returns_the_first_order(monkeypatch) -> None:
    """A retry that read the key just before the first call committed gets that order.

    A 409 for an ORDERED cart would tell the agent its own order failed.
    """
    world = _World()
    cart = world.cart(100)
    real_get = world.idempotency.get
    first = []

    def first_call_commits_now(buyer_id, key):
        record = real_get(buyer_id, key)
        monkeypatch.setattr(world.idempotency, "get", real_get)
        first.append(world.checkout(cart.cart_id))
        return record

    monkeypatch.setattr(world.idempotency, "get", first_call_commits_now)

    second = world.checkout(cart.cart_id)

    assert isinstance(second, Order)
    assert second == first[0]


def test_ordered_cart_with_a_new_key_is_not_ordered_again() -> None:
    """One cart gives one order; the door answers the cart in its ORDERED state with 409."""
    world = _World()
    cart = world.cart(100)
    world.checkout(cart.cart_id)

    result = world.checkout(cart.cart_id, key="k-2")

    assert result.state is CartState.ORDERED


def test_same_key_for_another_cart_is_a_conflict() -> None:
    """Replaying the first order for another cart would confirm goods that were not ordered."""
    world = _World()
    first = world.cart(100)
    other = world.cart(200)
    world.checkout(first.cart_id)

    with pytest.raises(ConflictError):
        world.checkout(other.cart_id)


def test_other_buyers_cart_is_not_found() -> None:
    """An agent must not learn about, or order, another buyer's cart."""
    world = _World()
    cart = world.cart(100)

    with pytest.raises(NotFoundError):
        world.checkout(cart.cart_id, buyer="hotel-2")


def test_place_with_an_approver_orders_a_cart_over_the_limit() -> None:
    """Above the limit a person's yes is what allows the order, and the order says who."""
    world = _World()
    cart = world.cart(1000)
    user = User(user_id="hotel-1-main", buyer_id=samples.BUYER_ID, role=UserRole.MAIN_USER)

    order = world.service.place(cart, user)

    assert isinstance(order, Order)
    assert order.approved_by == "hotel-1-main"


def test_approved_order_records_are_in_the_approval_phase() -> None:
    """The person's yes, the policy rerun and the order are one approval step on the run page."""
    world = _World()
    cart = world.cart(1000)
    user = User(user_id="hotel-1-main", buyer_id=samples.BUYER_ID, role=UserRole.MAIN_USER)

    world.service.place(cart, user)

    (*_, approval, policy, order) = world.audit.for_cart(cart.cart_id)
    assert [approval.step, policy.step, order.step] == [
        AuditStep.APPROVAL,
        AuditStep.POLICY,
        AuditStep.ORDER,
    ]
    assert {approval.phase, policy.phase, order.phase} == {FlowPhase.APPROVAL}
    assert order.sentence == "The order was committed at the signed price: 1,010.00 EUR ex VAT."


def test_get_order_is_only_for_its_buyer() -> None:
    """Another buyer gets the same 404 as for an unknown id."""
    world = _World()
    order = world.checkout(world.cart(100).cart_id)

    assert world.service.get_order(samples.BUYER_ID, order.order_id) == order
    with pytest.raises(NotFoundError):
        world.service.get_order("hotel-2", order.order_id)
    with pytest.raises(NotFoundError):
        world.service.get_order(samples.BUYER_ID, "ord_unknown")


def test_postgres_order_round_trip_keeps_the_signed_body(database: Database) -> None:
    """The jsonb store must give back the exact body that was signed, money and gtin too."""
    world = _World(database=database)
    cart = world.cart(100)

    order = world.checkout(cart.cart_id)

    assert world.orders.get(order.order_id) == order
    assert world.carts.get(cart.cart_id).state is CartState.ORDERED


def test_postgres_keeps_the_new_state_behind_a_409(database: Database) -> None:
    """A raise would roll the change back; the door's 409 must match what get_cart reads."""
    world = _World(database=database)
    cart = world.cart(100)
    world.raise_limit(2, Decimal("50.00"))

    world.checkout(cart.cart_id)

    assert world.cart_service.get_cart(samples.BUYER_ID, cart.cart_id).state is (
        CartState.PENDING_APPROVAL
    )
    assert world.steps(cart.cart_id)[-1] is AuditStep.POLICY


# 299.97 EUR and 300.98 EUR: each cart is under the 500 EUR day limit, both together are over.
_HALF_DAY_QTYS = (297, 298)


def test_second_auto_cart_for_the_day_waits_at_checkout() -> None:
    """Both carts were AUTO when made. The binding check is at checkout, with the placed orders."""
    world = _World()
    first, second = (world.cart(qty) for qty in _HALF_DAY_QTYS)

    order = world.checkout(first.cart_id, key="k-1")
    held = world.checkout(second.cart_id, key="k-2")

    assert isinstance(order, Order)
    assert held.state is CartState.PENDING_APPROVAL
    assert held.reason_codes == (ReasonCode.OVER_DAILY_AUTO_LIMIT,)


def test_postgres_racing_checkouts_never_pass_the_day_limit(database: Database) -> None:
    """Without the day lock both checkouts read no order for the day, and both place one."""
    world = _World(database=database)
    carts = [world.cart(qty) for qty in _HALF_DAY_QTYS]
    world.rendezvous.barrier = threading.Barrier(len(carts))
    results: list[Order | Cart | Exception] = []

    def checkout(index: int) -> None:
        try:
            results.append(world.checkout(carts[index].cart_id, key=f"k-{index}"))
        # Kept, not raised: an error in a thread would not fail the test.
        except Exception as error:
            results.append(error)

    threads = [threading.Thread(target=checkout, args=(index,)) for index in range(len(carts))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [error for error in results if isinstance(error, Exception)] == []
    (order,) = [result for result in results if isinstance(result, Order)]
    (held,) = [result for result in results if not isinstance(result, Order)]
    assert held.reason_codes == (ReasonCode.OVER_DAILY_AUTO_LIMIT,)
    assert world.orders.for_day(samples.BUYER_ID, MONDAY) == [order]
