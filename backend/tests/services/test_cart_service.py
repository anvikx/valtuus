import dataclasses
from collections.abc import Sequence
from datetime import date, datetime, timedelta
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
from app.domain.cart import CartDraft, CartLineInput, CartRevision, PricedLine
from app.domain.enums import (
    AuditStep,
    CartState,
    Decision,
    FlowPhase,
    ReasonCode,
    RevisionAuthor,
    StockModel,
)
from app.domain.errors import ConflictError, GatewayError, InvalidRequestError, NotFoundError
from app.domain.idempotency import IdempotencyRecord
from app.domain.mandate import Mandate
from app.domain.offer import Offer, OfferLine
from app.domain.order import Order
from app.domain.policy.check import CheckResult, PolicyCheck, PolicyContext
from app.domain.policy.duplicate_order import DuplicateOrder
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from app.domain.policy.previously_rejected import PreviouslyRejected
from app.domain.policy.product_safety import ProductSafety
from app.domain.policy.stock_check import StockCheck
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.mandate_service import MandateService
from tests.adapters import samples
from tests.fakes.offer_data import CLOSING, MILK_ID, MONDAY, NOW, FakeCatalog, product

_LIMIT = Decimal("500.00")
_KEY = "k-1"
_REVISE_KEY = "k-r1"
_OAT_ID = "465039"
_TUESDAY = MONDAY + timedelta(days=1)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.at = now

    def now(self) -> datetime:
        return self.at


def _auto_order(order_id: str, cart_id: str, delivery_date: date) -> Order:
    order = samples.order(order_id, cart_id, delivery_date=delivery_date)
    return dataclasses.replace(order, approved_by=None)


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
        extra_check: PolicyCheck | None = None,
    ) -> None:
        self.clock = _Clock(NOW)
        self.offers = InMemoryOfferRepository()
        self.carts = InMemoryCartRepository()
        self.revisions = InMemoryCartRevisionRepository()
        self.orders = InMemoryOrderRepository()
        self.idempotency = idempotency or InMemoryIdempotencyRepository()
        self.mandates = InMemoryMandateRepository()
        self.audit = InMemoryAuditRepository()
        unit_of_work = InMemoryUnitOfWork()
        audit = AuditService(self.audit, self.carts, self.offers, self.clock, unit_of_work)
        for mandate in (_mandate(1, _LIMIT),) if mandates is None else mandates:
            self.mandates.add(mandate)

        checks = [
            OrderLimit(),
            StockCheck(),
            DuplicateOrder(),
            PreviouslyRejected(),
            *([extra_check] if extra_check else []),
        ]
        self.service = CartService(
            self.offers,
            self.carts,
            self.revisions,
            self.orders,
            self.idempotency,
            MandateService(self.mandates, self.clock, audit, unit_of_work),
            FakeCatalog(product()),
            PolicyEngine(checks),
            self.clock,
            audit,
            unit_of_work,
        )

    def create(self, *lines: CartLineInput, key: str = _KEY, buyer: str = samples.BUYER_ID):
        draft = CartDraft(lines=lines, request_text="milk for Monday", clarifications=())
        return self.service.create_cart(samples.agent_key(buyer_id=buyer), draft, key)

    def revise(self, cart_id: str, *lines: CartLineInput, base: int = 1, key: str = _REVISE_KEY):
        draft = CartDraft(lines=lines, request_text="make it 800", clarifications=())
        return self.service.revise_cart(samples.agent_key(), cart_id, base, draft, key)

    def withdraw(self, cart_id: str, buyer: str = samples.BUYER_ID):
        return self.service.withdraw_cart(samples.agent_key(buyer_id=buyer), cart_id)

    def steps(self, cart_id: str) -> list[AuditStep]:
        return [record.step for record in self.audit.for_cart(cart_id)]

    def numbers(self, cart_id: str) -> list[int]:
        return [revision.cart.revision for revision in self.revisions.for_cart(cart_id)]


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
    assert cart.reason_sentences == ("1,010.00 EUR is over the 500.00 EUR limit.",)
    assert cart.current_reason_codes == (ReasonCode.OVER_AUTO_LIMIT,)


def test_partial_stock_waits_for_the_main_user() -> None:
    """Valio Aimo can deliver only part of what the kitchen needs, so a person decides."""
    world = _world_with_offer(_offer("o_1", _line(available_qty=50, sales_units_needed=100)))

    cart = world.create(_buy(50))

    assert cart.state is CartState.PENDING_APPROVAL
    assert cart.reason_codes == (ReasonCode.PARTIAL_AVAILABILITY,)
    assert cart.reason_sentences == ("Only 50 of 100 in stock.",)


def test_more_than_the_confirmed_stock_is_denied() -> None:
    """Valio Aimo cannot deliver it, so not even a person may order it."""
    world = _world_with_offer(_offer("o_1", _line(available_qty=50, sales_units_needed=100)))

    cart = world.create(_buy(100))

    assert cart.state is CartState.DENIED
    assert cart.decision is Decision.DENY
    assert cart.reason_codes == (ReasonCode.PARTIAL_AVAILABILITY,)


def test_unconfirmed_stock_waits_for_the_main_user() -> None:
    """A terminal product has no stock answer, so the agent may not order it alone."""
    world = _world_with_offer(_offer("o_1", _line(stock_model=StockModel.TERMINAL)))

    cart = world.create(_buy(10))

    assert cart.state is CartState.PENDING_APPROVAL
    assert cart.reason_codes == (ReasonCode.STOCK_UNCONFIRMED,)


def test_rerun_keeps_the_stock_facts_of_the_offer() -> None:
    """Checkout and approve rerun the policy from the stored cart, not from the offer."""
    world = _world_with_offer(_offer("o_1", _line(available_qty=50, sales_units_needed=100)))
    cart = world.create(_buy(50))

    result = world.service.current_policy(world.carts.get(cart.cart_id), NOW).result

    assert result.decision is Decision.HUMAN
    assert [reason.reason_code for reason in result.reasons] == [ReasonCode.PARTIAL_AVAILABILITY]


def test_same_order_again_names_the_earlier_order() -> None:
    """The main user must see which order this cart may repeat before they approve it."""
    world = _world_with_offer()
    first = world.create(_buy(100))
    earlier = _auto_order("o_9", first.cart_id, MONDAY)
    milk = dataclasses.replace(earlier.lines[0], product_id=MILK_ID, qty=100)
    world.orders.add(dataclasses.replace(earlier, lines=(milk,), placed_at=NOW))

    cart = world.create(_buy(100), key="k-2")

    assert cart.state is CartState.PENDING_APPROVAL
    assert cart.reason_codes == (ReasonCode.DUPLICATE_ORDER,)
    assert cart.duplicate_of_order_id == "o_9"


def test_rejected_cart_sent_again_is_denied_with_the_reason() -> None:
    """A person's no holds. The agent gets the reason, so it can change the cart."""
    world = _world_with_offer()
    first = world.create(_buy(100))
    rejected = dataclasses.replace(
        first,
        state=CartState.REJECTED,
        decided_at=NOW,
        reject_reason="We have milk.",
    )
    world.carts.save(rejected)

    cart = world.create(_buy(100), key="k-2")

    assert cart.state is CartState.DENIED
    assert cart.reason_codes == (ReasonCode.PREVIOUSLY_REJECTED,)
    assert cart.previous_reject_reason == "We have milk."


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


def test_new_cart_is_revision_one_by_the_agent() -> None:
    """Every later change is shown against what the agent first asked for."""
    world = _world_with_offer()

    cart = world.create(_buy(1000))

    assert cart.revision == 1
    assert world.revisions.for_cart(cart.cart_id) == [
        CartRevision(cart, RevisionAuthor.AGENT, NOW),
    ]


def test_run_1_cart_and_policy_records_read_as_plain_sentences() -> None:
    """The main user reads the trail, not the fields, so each step must say what happened."""
    world = _world_with_offer()

    cart = world.create(_buy(1000))

    cart_record, policy_record = world.audit.for_cart(cart.cart_id)
    assert cart_record.phase is FlowPhase.ORDER
    assert cart_record.sentence == (
        "The agent built a cart with 464306. 1,010.00 EUR ex VAT, fixed price."
    )
    assert policy_record.phase is FlowPhase.APPROVAL
    assert policy_record.sentence == (
        "The policy sent the cart to a person: 1,010.00 EUR is over the 500.00 EUR limit."
    )


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


def test_delivery_day_total_counts_only_auto_orders_on_that_date() -> None:
    """The page shows the total the daily limit checks. A person approved the other orders."""
    world = _world_with_offer()
    world.orders.add(_auto_order("o_1", "c_auto", MONDAY))
    world.orders.add(samples.order("o_2", "c_approved", delivery_date=MONDAY))
    world.orders.add(_auto_order("o_3", "c_other_day", _TUESDAY))

    cart = world.create(_buy(100))

    assert cart.delivery_day_total_ex_vat == samples.LARGE_MONEY + Decimal("101.00")


def test_delivery_day_total_takes_the_highest_date() -> None:
    """With lines on two dates, the larger date total is the one near its limit."""
    world = _world_with_offer(_offer("o_1"), _offer("o_2", _line(_OAT_ID, available_date=_TUESDAY)))
    world.orders.add(_auto_order("o_1", "c_old", _TUESDAY))

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
    assert list(context.products) == [MILK_ID]


def _milk_rules(version: int, *forbidden: str) -> Mandate:
    return dataclasses.replace(
        _mandate(version, _LIMIT),
        required_attributes=(),
        forbidden_allergens=forbidden,
    )


def test_cart_with_a_forbidden_allergen_is_denied() -> None:
    """The agent can skip search and send any product id, so the cart applies the rules."""
    world = _world_with_offer(mandates=[_milk_rules(1, "AM")], extra_check=ProductSafety())

    cart = world.create(_buy(10))

    assert cart.state is CartState.DENIED
    assert cart.reason_codes == (ReasonCode.FORBIDDEN_ALLERGEN,)


def test_rerun_applies_an_allergen_forbidden_after_the_cart() -> None:
    """Checkout and approve use the mandate of now, not the one of the cart."""
    world = _world_with_offer(mandates=[_milk_rules(1)], extra_check=ProductSafety())
    cart = world.create(_buy(10))
    world.mandates.add(_milk_rules(2, "AM"))

    result = world.service.current_policy(world.carts.get(cart.cart_id), NOW).result

    assert cart.state is CartState.AUTO
    assert result.decision is Decision.DENY
    assert [reason.reason_code for reason in result.reasons] == [ReasonCode.FORBIDDEN_ALLERGEN]


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
    if world.offers.get("of_1") is None:
        world.offers.add(samples.offer())
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


def test_revise_makes_the_next_revision_and_keeps_the_one_before() -> None:
    """A person approves one revision by its number, so an earlier one must never change."""
    world = _world_with_offer()
    first = world.create(_buy(1000))

    revised = world.revise(first.cart_id, _buy(100))

    assert revised.cart_id == first.cart_id
    assert revised.revision == 2
    assert [line.qty for line in revised.lines] == [100]
    assert revised.request_text == "make it 800"
    assert world.carts.get(first.cart_id) == revised
    assert world.revisions.for_cart(first.cart_id) == [
        CartRevision(first, RevisionAuthor.AGENT, NOW),
        CartRevision(revised, RevisionAuthor.AGENT, NOW),
    ]


def test_revise_runs_the_policy_from_the_start() -> None:
    """The new lines can cross the limit, so the decision of revision 1 must not carry over."""
    world = _world_with_offer()
    first = world.create(_buy(100))

    revised = world.revise(first.cart_id, _buy(1000))

    assert first.state is CartState.AUTO
    assert revised.state is CartState.PENDING_APPROVAL
    assert revised.decision is Decision.HUMAN
    assert revised.reason_codes == (ReasonCode.OVER_AUTO_LIMIT,)
    assert revised.total_ex_vat == Decimal("1010.00")


def test_revise_into_the_limit_lets_the_agent_check_out() -> None:
    """A smaller change can bring the cart back inside the mandate."""
    world = _world_with_offer()
    first = world.create(_buy(1000))

    revised = world.revise(first.cart_id, _buy(100))

    assert revised.state is CartState.AUTO
    assert revised.reason_codes == ()


def test_revise_writes_a_cart_and_a_policy_record_for_the_revision() -> None:
    """The main user reads the trail, so each revision says who changed what, and why."""
    world = _world_with_offer()
    first = world.create(_buy(100))

    world.revise(first.cart_id, _buy(1000))

    *_, cart_record, policy_record = world.audit.for_cart(first.cart_id)
    assert world.steps(first.cart_id) == [AuditStep.CART, AuditStep.POLICY] * 2
    assert cart_record.sentence == (
        f"Revision 2 by the agent: Milk {MILK_ID} 100 to 1,000. 1,010.00 EUR ex VAT, fixed price."
    )
    assert cart_record.input_data["base_revision"] == 1
    assert cart_record.output_data["revision"] == 2
    assert policy_record.decision is Decision.HUMAN


def test_revise_from_an_old_revision_is_refused_and_changes_nothing() -> None:
    """Two people changed the same cart. The later one must not erase the first change."""
    world = _world_with_offer()
    first = world.create(_buy(1000))
    second = world.revise(first.cart_id, _buy(800))

    with pytest.raises(ConflictError) as error:
        world.revise(first.cart_id, _buy(600), base=1, key="k-r2")

    assert "revision 2" in error.value.message
    assert "base_revision 2" in error.value.next_step
    assert world.carts.get(first.cart_id) == second
    assert world.numbers(first.cart_id) == [1, 2]
    assert world.idempotency.get(samples.BUYER_ID, "k-r2") is None


@pytest.mark.parametrize(
    "state",
    [CartState.ORDERED, CartState.REJECTED, CartState.DENIED, CartState.EXPIRED],
)
def test_closed_cart_cannot_be_revised(state: CartState) -> None:
    """After the order or a final no, a change needs a new cart and a new approval."""
    world = _world_with_offer()
    first = world.create(_buy(1000))
    closed = dataclasses.replace(first, state=state)
    world.carts.save(closed)

    with pytest.raises(ConflictError) as error:
        world.revise(first.cart_id, _buy(800))

    assert state in error.value.message
    assert world.carts.get(first.cart_id) == closed
    assert world.numbers(first.cart_id) == [1]


def test_ordered_cart_tells_the_agent_to_make_a_new_cart() -> None:
    """The agent says "Already ordered" to the buyer and offers a new order."""
    world = _world_with_offer()
    first = world.create(_buy(100))
    world.carts.save(dataclasses.replace(first, state=CartState.ORDERED))

    with pytest.raises(ConflictError) as error:
        world.revise(first.cart_id, _buy(80))

    assert "already ordered" in error.value.message
    assert "new cart" in error.value.next_step


def test_revise_after_the_deadline_keeps_the_expiry() -> None:
    """No order can reach Valio Aimo after closing time, so the cart ends, also on a change."""
    world = _world_with_offer()
    first = world.create(_buy(1000))
    world.clock.at = CLOSING

    with pytest.raises(ConflictError):
        world.revise(first.cart_id, _buy(800))

    assert world.carts.get(first.cart_id).state is CartState.EXPIRED
    assert world.numbers(first.cart_id) == [1]


def test_revise_with_a_closed_line_is_refused_and_nothing_is_stored() -> None:
    """A line past its closing time cannot be ordered, so the agent must get new offers."""
    world = _world_with_offer(
        _offer("o_1"),
        _offer("o_2", _line(_OAT_ID, closing_time=NOW)),
    )
    first = world.create(_buy(1000))

    with pytest.raises(ConflictError) as error:
        world.revise(first.cart_id, _buy(1000), _buy(1, offer_id="o_2", product_id=_OAT_ID))

    assert ReasonCode.CUTOFF_PASSED in error.value.message
    assert world.carts.get(first.cart_id) == first
    assert world.numbers(first.cart_id) == [1]
    assert world.idempotency.get(samples.BUYER_ID, _REVISE_KEY) is None


def test_revision_is_not_a_duplicate_of_the_one_before() -> None:
    """The duplicate check looks for an earlier order, never for the cart's own revisions."""
    world = _world_with_offer()
    first = world.create(_buy(100))

    revised = world.revise(first.cart_id, _buy(100))

    assert revised.state is CartState.AUTO
    assert ReasonCode.DUPLICATE_ORDER not in revised.reason_codes
    assert revised.duplicate_of_order_id is None


def test_revise_retry_with_the_same_key_returns_the_revision() -> None:
    """A lost answer must not make revision 3, or the agent's retry would fail on its base."""
    world = _world_with_offer()
    first = world.create(_buy(1000))

    revised = world.revise(first.cart_id, _buy(800))
    again = world.revise(first.cart_id, _buy(800))

    assert again == revised
    assert world.numbers(first.cart_id) == [1, 2]
    assert world.steps(first.cart_id) == [AuditStep.CART, AuditStep.POLICY] * 2


class _LateKeyRead(InMemoryIdempotencyRepository):
    """Once armed, the next read misses: that call read the key before the first call committed."""

    def __init__(self) -> None:
        super().__init__()
        self.is_armed = False

    def get(self, buyer_id: str, key: str) -> IdempotencyRecord | None:
        if self.is_armed:
            self.is_armed = False
            return None

        return super().get(buyer_id, key)


def test_revise_retry_that_waited_on_the_lock_returns_the_revision() -> None:
    """A retry that waited behind the first call must not get a 409 on its own base."""
    keys = _LateKeyRead()
    world = _world_with_offer(idempotency=keys)
    first = world.create(_buy(1000))
    revised = world.revise(first.cart_id, _buy(800))
    keys.is_armed = True

    again = world.revise(first.cart_id, _buy(800))

    assert again == revised
    assert world.numbers(first.cart_id) == [1, 2]


def test_same_revise_key_for_another_change_is_a_conflict() -> None:
    """Replaying the first change for a different body would order the wrong amount."""
    world = _world_with_offer()
    first = world.create(_buy(1000))
    world.revise(first.cart_id, _buy(800))

    with pytest.raises(ConflictError):
        world.revise(first.cart_id, _buy(600), base=2)


def test_other_buyers_cart_cannot_be_revised_or_withdrawn() -> None:
    """One answer for both, so an agent cannot probe or change other buyers' carts."""
    world = _world_with_offer()
    first = world.create(_buy(1000))
    other = samples.agent_key(buyer_id="hotel-2")
    draft = CartDraft(lines=(_buy(1),), request_text="mine now", clarifications=())

    with pytest.raises(NotFoundError):
        world.service.revise_cart(other, first.cart_id, 1, draft, _REVISE_KEY)
    with pytest.raises(NotFoundError):
        world.withdraw(first.cart_id, buyer="hotel-2")

    assert world.carts.get(first.cart_id) == first


def test_cart_with_no_revision_rows_keeps_its_base_on_revise() -> None:
    """A cart made by an older gateway has no rows. The change must still show what it was."""
    world = _world_with_offer()
    old = dataclasses.replace(world.create(_buy(1000)), cart_id="c_old")
    world.carts.add(old)

    revised = world.revise("c_old", _buy(800))

    assert world.revisions.for_cart("c_old") == [
        CartRevision(old, RevisionAuthor.AGENT, NOW),
        CartRevision(revised, RevisionAuthor.AGENT, NOW),
    ]


def test_withdraw_ends_an_open_cart_with_one_record() -> None:
    """The buyer said "forget it", so the main user must not approve the cart any more."""
    world = _world_with_offer()
    first = world.create(_buy(1000))

    withdrawn = world.withdraw(first.cart_id)

    assert withdrawn.state is CartState.WITHDRAWN
    assert world.carts.get(first.cart_id) == withdrawn
    assert world.steps(first.cart_id) == [AuditStep.CART, AuditStep.POLICY, AuditStep.CART]
    assert world.audit.for_cart(first.cart_id)[-1].sentence == "The agent withdrew the cart."


@pytest.mark.parametrize(
    "state",
    [
        CartState.ORDERED,
        CartState.REJECTED,
        CartState.DENIED,
        CartState.EXPIRED,
        CartState.WITHDRAWN,
    ],
)
def test_closed_cart_cannot_be_withdrawn(state: CartState) -> None:
    """A final state stays final. The 409 names it, so the agent knows what happened."""
    world = _world_with_offer()
    first = world.create(_buy(1000))
    closed = dataclasses.replace(first, state=state)
    world.carts.save(closed)

    with pytest.raises(ConflictError) as error:
        world.withdraw(first.cart_id)

    assert state in error.value.message
    assert world.carts.get(first.cart_id) == closed


def test_withdrawn_cart_cannot_be_revised() -> None:
    """WITHDRAWN is final. A new wish needs a new cart."""
    world = _world_with_offer()
    first = world.create(_buy(1000))
    world.withdraw(first.cart_id)

    with pytest.raises(ConflictError, match=CartState.WITHDRAWN):
        world.revise(first.cart_id, _buy(800))
