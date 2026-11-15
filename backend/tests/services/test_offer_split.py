from dataclasses import replace
from decimal import Decimal

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import (
    InMemoryCartRepository,
    InMemoryCartRevisionRepository,
    InMemoryIdempotencyRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryOrderRepository,
    InMemorySearchSetRepository,
    InMemoryUnitOfWork,
)
from app.adapters.signer import NullSigner
from app.domain.cart import CartDraft, CartLineInput
from app.domain.enums import AuditStep, Decision, ReasonCode
from app.domain.offer import Offer
from app.domain.policy.auto_order_switch import AutoOrderSwitch
from app.domain.policy.checks.cutoff import Cutoff
from app.domain.policy.checks.envelope import KnownProduct, Quantity
from app.domain.policy.checks.line_limit import LineLimit
from app.domain.policy.checks.product_rules import Brand, Substitute
from app.domain.policy.checks.request_rules import Delivery, RequestQuantity
from app.domain.policy.daily_limit import DailyLimit
from app.domain.policy.duplicate_order import DuplicateOrder
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from app.domain.policy.previously_rejected import PreviouslyRejected
from app.domain.policy.product_safety import ProductSafety
from app.domain.policy.stock_check import StockCheck
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.mandate_service import MandateService
from app.services.offer_service import OfferService
from tests.adapters import samples
from tests.fakes.offer_data import (
    NOW,
    FakeCatalog,
    FakePriceSource,
    price,
    product,
    query,
    stock,
)

_ARLA_ID = "469363"
_ARLA_NAME = "Arla Semi skimmed milkdrink 1 L UHT lactose free Suomesta"
_VALIO_ID = "464306"
_VALIO_NAME = "Valio Hyvä suomalainen Arki® Eila® semi skimmed milk drink 1 l lactose free"
_AUTO_LIMIT = Decimal("500.00")


class _Records:
    def __init__(self) -> None:
        self.records = []

    def append(self, record) -> None:
        self.records.append(record)


class _World:
    """Run 3: the mandate prefers Arla, which has 384 L, and Valio has plenty."""

    def __init__(self) -> None:
        self.clock = FixedClock(NOW)
        self.offers = InMemoryOfferRepository()
        self.carts = InMemoryCartRepository()
        self.records = _Records()
        mandates = InMemoryMandateRepository()
        mandates.add(
            replace(
                samples.mandate(),
                preferred_brands=("Arla",),
                max_auto_order_value=_AUTO_LIMIT,
                max_auto_value_per_delivery_date=_AUTO_LIMIT,
                max_line_value=None,
                required_attributes=(),
                forbidden_allergens=(),
            )
        )

        unit_of_work = InMemoryUnitOfWork()
        audit = AuditService(self.records, self.carts, self.offers, self.clock, unit_of_work)
        mandate_service = MandateService(mandates, self.clock, audit, unit_of_work)
        catalog = FakeCatalog(
            product(_ARLA_ID, brand="Arla", name=_ARLA_NAME),
            product(_VALIO_ID, brand="Valio", name=_VALIO_NAME),
        )
        source = FakePriceSource(
            [price(_ARLA_ID, "0.90"), price(_VALIO_ID, "1.01")],
            [stock(_ARLA_ID, amount=384), stock(_VALIO_ID)],
        )
        self.offer_service = OfferService(
            catalog,
            source,
            self.offers,
            NullSigner(),
            InMemorySearchSetRepository(),
            self.clock,
            audit,
            unit_of_work,
            2,
            mandates,
        )
        self.cart_service = CartService(
            self.offers,
            self.carts,
            InMemoryCartRevisionRepository(),
            InMemoryOrderRepository(),
            InMemoryIdempotencyRepository(),
            mandate_service,
            catalog,
            PolicyEngine(
                [
                    AutoOrderSwitch(),
                    KnownProduct(),
                    Quantity(),
                    OrderLimit(),
                    LineLimit(),
                    Brand(),
                    Substitute(),
                    Delivery(),
                    RequestQuantity(),
                    Cutoff(),
                    DailyLimit(),
                    StockCheck(),
                    DuplicateOrder(),
                    PreviouslyRejected(),
                    ProductSafety(),
                ]
            ),
            self.clock,
            audit,
            unit_of_work,
        )

    def offer(self, **fields) -> Offer:
        ask = query(_ARLA_ID, _VALIO_ID, **fields)
        return self.offer_service.get_offers(samples.agent_key(), ask)


def _split_pairs(offer: Offer) -> list[tuple[str, int]]:
    assert offer.proposed_split is not None
    return [(line.product_id, line.qty) for line in offer.proposed_split.lines]


def test_the_mandate_brands_make_the_run_3_split() -> None:
    """The agent never sends brands in run 3: the buyer's mandate must drive the split."""
    world = _World()

    offer = world.offer()

    assert _split_pairs(offer) == [(_ARLA_ID, 384), (_VALIO_ID, 616)]
    assert offer.proposed_split.unfilled_qty == 0
    assert offer.proposed_split.lines[1].reason_codes == (ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,)


def test_the_audit_record_keeps_the_split() -> None:
    """The record must show who was asked for what, or the split cannot be explained later."""
    world = _World()

    world.offer()

    (record,) = world.records.records
    assert record.step is AuditStep.OFFER
    assert record.output_data["split"] == {
        "lines": {_ARLA_ID: 384, _VALIO_ID: 616},
        "unfilled_qty": 0,
    }


def test_the_run_3_split_cart_needs_a_person() -> None:
    """Run 3 goes to the buyer: partial stock, another brand and over the auto limit."""
    world = _World()
    offer = world.offer()
    lines = tuple(
        CartLineInput(offer.offer_id, line.product_id, line.qty)
        for line in offer.proposed_split.lines
    )
    draft = CartDraft(lines=lines, request_text="1000 L milk", clarifications=())

    cart = world.cart_service.create_cart(samples.agent_key(), draft, "k-1")

    assert cart.decision is Decision.HUMAN
    assert {*cart.reason_codes} >= {
        ReasonCode.PARTIAL_AVAILABILITY,
        ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,
        ReasonCode.OVER_AUTO_LIMIT,
    }
