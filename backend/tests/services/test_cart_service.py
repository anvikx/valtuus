import dataclasses
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal

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
from app.domain.cart import CartDraft, CartLineInput, PricedLine
from app.domain.enums import AuditStep, CartState, Decision, ReasonCode
from app.domain.errors import ConflictError, GatewayError, InvalidRequestError, NotFoundError
from app.domain.idempotency import IdempotencyRecord
from app.domain.mandate import Mandate
from app.domain.offer import Offer, OfferLine
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.mandate_service import MandateService
from tests.adapters import samples
from tests.fakes.offer_data import CLOSING, MILK_ID, MONDAY, NOW

_LIMIT = Decimal("500.00")
_KEY = "k-1"
_OAT_ID = "465039"
_TUESDAY = MONDAY + timedelta(days=1)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


class _RacedKeys(InMemoryIdempotencyRepository):
    """Another call with the same key committed between our read and our insert."""

    def get(self, buyer_id: str, key: str) -> IdempotencyRecord | None:
        return None

    def add(self, record: IdempotencyRecord) -> None:
        raise ValueError(f"idempotency key {record.key} is used")


class _SpyCheck:
    def __init__(self) -> None:
        self.contexts: list[PolicyContext] = []

    def evaluate(self, lines: Sequence[PricedLine], context: PolicyContext) -> list[CheckResult]:
        self.contexts.append(context)
        return []


class _World:
    """The service on in-memory stores, with one mandate and a clock the test can move."""

    def __init__(
        self,
        idempotency: InMemoryIdempotencyRepository | None = None,
        mandates: Sequence[Mandate] | None = None,
        extra_check: _SpyCheck | None = None,
    ) -> None:
        self.clock = _Clock(NOW)
        self.offers = InMemoryOfferRepository()
        self.carts = InMemoryCartRepository()
        self.orders = InMemoryOrderRepository()
        self.idempotency = idempotency or InMemoryIdempotencyRepository()
        self.mandates = InMemoryMandateRepository()
        self.audit = InMemoryAuditRepository()
        unit_of_work = InMemoryUnitOfWork()
        audit = AuditService(self.audit, self.carts, self.offers, self.clock, unit_of_work)
        for mandate in (_mandate(1, _LIMIT),) if mandates is None else mandates:
            self.mandates.add(mandate)

        checks = [OrderLimit(), *([extra_check] if extra_check else [])]
        self.service = CartService(
            self.offers,
            self.carts,
            self.orders,
            self.idempotency,
            MandateService(self.mandates, self.clock, audit, unit_of_work),
            PolicyEngine(checks),
            self.clock,
            audit,
            unit_of_work,
        )

    def create(self, *lines: CartLineInput, key: str = _KEY, buyer: str = samples.BUYER_ID):
        draft = CartDraft(lines=lines, request_text="milk for Monday", clarifications=())
        return self.service.create_cart(samples.agent_key(buyer_id=buyer), draft, key)

    def steps(self, cart_id: str) -> list[AuditStep]:
        return [record.step for record in self.audit.for_cart(cart_id)]


def _mandate(version: int, limit: Decimal) -> Mandate:
    return dataclasses.replace(
        samples.mandate(version),
        max_auto_order_value=limit,
        max_auto_value_per_delivery_date=limit,
    )


def _line(product_id: str = MILK_ID, **changes: object) -> OfferLine:
    base = dataclasses.replace(
        samples.offer().lines[0],
        product_id=product_id,
        name=f"Milk {product_id}",
        unit_price=Decimal("1.01"),
        price_valid_from=date(2026, 9, 1),
        price_valid_to=date(2026, 12, 31),
        available_date=MONDAY,
        closing_time=CLOSING,
        substitute_for=None,
    )
    return dataclasses.replace(base, **changes)


def _offer(
    offer_id: str = "o_1",
    *lines: OfferLine,
    buyer: str = samples.BUYER_ID,
    valid_until: datetime = NOW + timedelta(minutes=15),
) -> Offer:
    return dataclasses.replace(
        samples.offer(offer_id),
        buyer_id=buyer,
        issued_at=NOW,
        valid_until=valid_until,
        lines=lines or (_line(),),
    )


def _buy(qty: int, offer_id: str = "o_1", product_id: str = MILK_ID) -> CartLineInput:
    return CartLineInput(offer_id=offer_id, product_id=product_id, qty=qty)


def _world_with_offer(*offers: Offer, **options: object) -> _World:
    world = _World(**options)
    for offer in offers or (_offer(),):
        world.offers.add(offer)

    return world


def test_prices_come_from_the_stored_offer() -> None:
    """The agent sends only ids and quantities, so it cannot set its own price."""
    world = _world_with_offer()

    cart = world.create(_buy(100))

    (line,) = cart.lines
    assert line.unit_price == Decimal("1.01")
    assert line.line_total == Decimal("101.00")
    assert line.name == f"Milk {MILK_ID}"
    assert line.delivery_date == MONDAY
    assert line.decision is Decision.AUTO
    assert cart.total_ex_vat == Decimal("101.00")
    assert cart.state is CartState.AUTO
    assert cart.decision is Decision.AUTO
    assert cart.current_decision is Decision.AUTO
    assert cart.reason_codes == ()
    assert cart.mandate_version == 1
    assert cart.buyer_id == samples.BUYER_ID
    assert cart.agent_name == "Claude Code"


def test_over_the_limit_waits_for_the_main_user() -> None:
    """Above the agent's limit only a person may say yes."""
    world = _world_with_offer()

    cart = world.create(_buy(1000))

    assert cart.state is CartState.PENDING_APPROVAL
    assert cart.decision is Decision.HUMAN
    assert cart.reason_codes == (ReasonCode.OVER_AUTO_LIMIT,)
    assert cart.reason_sentences == ("Total is over this agent's 500.00 EUR limit.",)
    assert cart.current_reason_codes == (ReasonCode.OVER_AUTO_LIMIT,)


def test_cart_is_stored_with_its_key_and_cart_and_policy_records() -> None:
    """The audit trail must show what the agent asked for and why the gateway decided."""
    world = _world_with_offer()

    cart = world.create(_buy(1000))

    assert world.carts.get(cart.cart_id) == cart
    assert world.idempotency.get(samples.BUYER_ID, _KEY).result_id == cart.cart_id
    cart_record, policy_record = world.audit.for_cart(cart.cart_id)
    assert cart_record.step is AuditStep.CART
    assert cart_record.input_data["request_text"] == "milk for Monday"
    assert policy_record.step is AuditStep.POLICY
    assert policy_record.decision is Decision.HUMAN
    assert policy_record.reason_codes == (ReasonCode.OVER_AUTO_LIMIT,)
    assert policy_record.mandate_version == 1


def test_unknown_offer_and_other_buyers_offer_get_the_same_404() -> None:
    """A different answer would tell an agent which offer ids exist for other buyers."""
    world = _world_with_offer(_offer("o_2", buyer="hotel-2"))

    with pytest.raises(NotFoundError) as unknown:
        world.create(_buy(1, offer_id="o_9"))
    with pytest.raises(NotFoundError) as foreign:
        world.create(_buy(1, offer_id="o_2"), key="k-2")

    assert unknown.value.message.replace("o_9", "o_2") == foreign.value.message


def test_product_not_in_the_offer_is_refused() -> None:
    """A line must point at a priced offer line, or there is no price to use."""
    world = _world_with_offer()

    with pytest.raises(InvalidRequestError):
        world.create(_buy(1, product_id=_OAT_ID))


def test_same_product_twice_is_refused() -> None:
    """Reasons point at a line by product, so two lines for one product would mix them up."""
    world = _world_with_offer(_offer("o_1"), _offer("o_2"))

    with pytest.raises(InvalidRequestError):
        world.create(_buy(1), _buy(2, offer_id="o_2"))


def test_line_past_its_closing_time_is_refused_and_nothing_is_stored() -> None:
    """No order can reach Valio Aimo for that date, so the agent must get new offers."""
    world = _world_with_offer()
    world.clock.at = CLOSING

    with pytest.raises(ConflictError) as error:
        world.create(_buy(1))

    assert ReasonCode.CUTOFF_PASSED in error.value.message
    assert "new offers" in error.value.next_step
    assert world.carts.for_buyer(samples.BUYER_ID) == []
    assert world.idempotency.get(samples.BUYER_ID, _KEY) is None


def test_delivery_after_the_price_end_is_refused() -> None:
    """After price_valid_to there is no fixed price for the delivery date."""
    world = _world_with_offer(_offer("o_1", _line(price_valid_to=MONDAY - timedelta(days=1))))

    with pytest.raises(ConflictError) as error:
        world.create(_buy(1))

    assert ReasonCode.PRICE_NOT_VALID_FOR_DATE in error.value.message


def test_offer_past_valid_until_still_makes_a_cart() -> None:
    """valid_until limits only the stock snapshot. Checkout and approve check stock again."""
    world = _world_with_offer()
    world.clock.at = NOW + timedelta(minutes=20)

    cart = world.create(_buy(1))

    assert cart.state is CartState.AUTO
    assert cart.valid_until == NOW + timedelta(minutes=15)


def test_approve_before_and_valid_until_are_the_earliest_of_the_lines() -> None:
    """The cart is only as good as its first deadline and its oldest stock snapshot."""
    early_close = CLOSING - timedelta(hours=2)
    early_offer = NOW + timedelta(minutes=5)
    world = _world_with_offer(
        _offer("o_1"),
        _offer("o_2", _line(_OAT_ID, closing_time=early_close), valid_until=early_offer),
    )

    cart = world.create(_buy(1), _buy(1, offer_id="o_2", product_id=_OAT_ID))

    assert cart.approve_before == early_close
    assert cart.valid_until == early_offer


def test_retry_with_the_same_key_returns_the_first_cart() -> None:
    """A lost answer must not make a second cart or a second audit trail."""
    world = _world_with_offer()

    first = world.create(_buy(100))
    second = world.create(_buy(100))

    assert second == first
    assert world.carts.for_buyer(samples.BUYER_ID) == [first]
    assert world.steps(first.cart_id) == [AuditStep.CART, AuditStep.POLICY]


def test_same_key_with_another_cart_is_a_conflict() -> None:
    """Replaying the first cart for a different request would buy the wrong goods."""
    world = _world_with_offer()
    world.create(_buy(100))

    with pytest.raises(ConflictError):
        world.create(_buy(200))


def test_key_race_is_a_conflict_that_asks_for_a_retry() -> None:
    """The losing call must not store a second cart; its retry then replays the winner."""
    world = _world_with_offer(idempotency=_RacedKeys())

    with pytest.raises(ConflictError) as error:
        world.create(_buy(100))

    assert "same Idempotency-Key" in error.value.next_step
    assert world.carts.for_buyer(samples.BUYER_ID) == []


def test_missing_mandate_is_a_server_error_not_a_404() -> None:
    """A 404 would make the agent think its offer or cart is gone. It is a seed fault."""
    world = _world_with_offer(mandates=())

    with pytest.raises(RuntimeError) as error:
        world.create(_buy(1))

    assert not isinstance(error.value, GatewayError)


def test_delivery_day_total_counts_every_placed_order_on_that_date() -> None:
    """The page says what the whole delivery costs, approved orders included."""
    world = _world_with_offer()
    world.orders.add(samples.order("o_1", "c_old", delivery_date=MONDAY))
    world.orders.add(samples.order("o_2", "c_other_day", delivery_date=_TUESDAY))

    cart = world.create(_buy(100))

    assert cart.delivery_day_total_ex_vat == samples.LARGE_MONEY + Decimal("101.00")


def test_delivery_day_total_takes_the_highest_date() -> None:
    """With lines on two dates, the larger date total is the one near its limit."""
    world = _world_with_offer(_offer("o_1"), _offer("o_2", _line(_OAT_ID, available_date=_TUESDAY)))
    world.orders.add(samples.order("o_1", "c_old", delivery_date=_TUESDAY))

    cart = world.create(_buy(100), _buy(10, offer_id="o_2", product_id=_OAT_ID))

    assert cart.delivery_day_total_ex_vat == samples.LARGE_MONEY + Decimal("10.10")


def test_policy_sees_the_day_orders_and_recent_rejects() -> None:
    """Empty facts would let the later day limit and reject checks pass by mistake."""
    spy = _SpyCheck()
    world = _world_with_offer(extra_check=spy)
    old_reject = dataclasses.replace(
        samples.cart("c_old", CartState.REJECTED),
        decided_at=NOW - timedelta(hours=2),
    )
    recent_reject = dataclasses.replace(
        samples.cart("c_recent", CartState.REJECTED),
        decided_at=NOW - timedelta(minutes=10),
    )
    world.orders.add(samples.order("o_1", "c_placed", delivery_date=MONDAY))
    world.carts.add(old_reject)
    world.carts.add(recent_reject)

    world.create(_buy(100))

    (context,) = spy.contexts
    assert [order.order_id for order in context.day_orders] == ["o_1"]
    assert [cart.cart_id for cart in context.recent_rejects] == ["c_recent"]
    assert context.now == NOW


def test_other_buyers_cart_is_not_found() -> None:
    """One buyer's agent must not read another buyer's cart."""
    world = _world_with_offer()
    cart = world.create(_buy(100))

    with pytest.raises(NotFoundError):
        world.service.get_cart("hotel-2", cart.cart_id)
    with pytest.raises(NotFoundError):
        world.service.get_cart(samples.BUYER_ID, "c_missing")


def test_read_after_the_deadline_expires_the_cart_once() -> None:
    """The cart expires on read, with no background job, and the trail shows it one time."""
    world = _world_with_offer()
    cart = world.create(_buy(1000))
    world.clock.at = CLOSING

    expired = world.service.get_cart(samples.BUYER_ID, cart.cart_id)
    again = world.service.get_cart(samples.BUYER_ID, cart.cart_id)

    assert expired.state is CartState.EXPIRED
    assert expired.reason_codes == (ReasonCode.CUTOFF_PASSED,)
    assert expired.reason_sentences == (
        "The order deadline Sun 15 Nov 17:00 has passed. Get new offers.",
    )
    assert world.carts.get(cart.cart_id) == expired
    assert again == expired
    assert world.steps(cart.cart_id) == [AuditStep.CART, AuditStep.POLICY, AuditStep.CART]


def test_replay_after_the_deadline_expires_the_cart_and_writes_one_record() -> None:
    """A replay reads through get_cart, so it expires the cart. That is right: keep it."""
    world = _world_with_offer()
    cart = world.create(_buy(1000))
    world.clock.at = CLOSING

    replay = world.create(_buy(1000))

    assert replay.state is CartState.EXPIRED
    assert world.steps(cart.cart_id) == [AuditStep.CART, AuditStep.POLICY, AuditStep.CART]


def test_closed_cart_is_not_changed_on_read() -> None:
    """A rejected or ordered cart keeps its end state after the deadline."""
    world = _world_with_offer()
    rejected = samples.cart("c_1", CartState.REJECTED)
    world.carts.add(rejected)

    assert world.service.get_cart(samples.BUYER_ID, "c_1") == rejected
    assert world.audit.for_cart("c_1") == []


def test_current_decision_follows_a_new_mandate() -> None:
    """The main user sees what checkout would decide now, not what the old rules said."""
    world = _world_with_offer()
    cart = world.create(_buy(100))
    world.mandates.add(_mandate(2, Decimal("50.00")))

    read = world.service.get_cart(samples.BUYER_ID, cart.cart_id)

    assert read.state is CartState.AUTO
    assert read.decision is Decision.AUTO
    assert read.current_decision is Decision.HUMAN
    assert read.current_reason_codes == (ReasonCode.OVER_AUTO_LIMIT,)
    assert world.carts.get(cart.cart_id) == cart


def _stored(world: _World, cart_id: str, state: CartState, deadline: datetime, **changes):
    cart = dataclasses.replace(samples.cart(cart_id, state), approve_before=deadline, **changes)
    world.carts.add(cart)
    return cart


def test_inbox_shows_pending_carts_first_then_the_latest_decided() -> None:
    """The main user acts on the most urgent cart first, then sees what was decided last."""
    world = _World()
    later = NOW + timedelta(hours=2)
    sooner = NOW + timedelta(hours=1)
    _stored(world, "c_old", CartState.ORDERED, NOW - timedelta(days=2))
    _stored(world, "c_late", CartState.PENDING_APPROVAL, later)
    _stored(world, "c_new", CartState.REJECTED, NOW - timedelta(days=1))
    _stored(world, "c_soon", CartState.PENDING_APPROVAL, sooner)
    _stored(world, "c_auto", CartState.AUTO, later)

    inbox = world.service.list_for_inbox(samples.BUYER_ID)

    assert [cart.cart_id for cart in inbox] == ["c_soon", "c_late", "c_auto", "c_new", "c_old"]


def test_inbox_expires_a_pending_cart_past_its_deadline() -> None:
    """An approve button on a dead cart only gives a 409, so the inbox shows it as expired."""
    world = _World()
    _stored(world, "c_1", CartState.PENDING_APPROVAL, NOW)

    [cart] = world.service.list_for_inbox(samples.BUYER_ID)

    assert cart.state is CartState.EXPIRED
    assert world.steps("c_1") == [AuditStep.CART]


def test_inbox_shows_the_current_decision_by_the_current_mandate() -> None:
    """After the main user raises the limit, the inbox shows the cart can go through now."""
    world = _World()
    _stored(world, "c_1", CartState.PENDING_APPROVAL, NOW + timedelta(hours=1))
    world.mandates.add(_mandate(2, Decimal("5000.00")))

    [cart] = world.service.list_for_inbox(samples.BUYER_ID)

    assert cart.current_decision is Decision.AUTO


def test_inbox_lists_only_the_buyers_own_carts() -> None:
    """One buyer must not see another buyer's carts."""
    world = _World()
    _stored(
        world, "c_other", CartState.PENDING_APPROVAL, NOW + timedelta(hours=1), buyer_id="hotel-2"
    )

    assert world.service.list_for_inbox(samples.BUYER_ID) == []
