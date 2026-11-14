"""One collected unit test per current cart-rule row, using the complete PolicyEngine."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.cart import PricedLine
from app.domain.catalog import Allergens, ContentPerSalesUnit
from app.domain.enums import (
    AllergenStatus,
    AllergenType,
    CartState,
    Decision,
    ReasonCode,
    StockModel,
    Unit,
)
from app.domain.money import line_total
from app.domain.policy.auto_order_switch import AutoOrderSwitch
from app.domain.policy.baseline import build_baseline
from app.domain.policy.check import PolicyContext
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
from tests.adapters import samples
from tests.fakes.offer_data import product

_PRODUCT_ID = "p_2"
_QTY = 20
_UNIT_PRICE = Decimal("10.00")
_TOTAL = Decimal("200.00")
_LINE = PricedLine(
    offer_id="of_1",
    product_id=_PRODUCT_ID,
    name="Milk 1 l",
    qty=_QTY,
    unit_price=_UNIT_PRICE,
    line_total=_TOTAL,
    delivery_date=samples.DELIVERY_DATE,
    closing_time=samples.NOW + timedelta(days=1),
    substitute_for=None,
    stock_model=StockModel.STOCK,
    available_qty=1000,
    needed_qty=_QTY,
)
_PRODUCT = replace(
    product(_PRODUCT_ID),
    content_per_sales_unit=ContentPerSalesUnit(Decimal(1), Unit.PCS),
    attributes=("FREE_FROM_LACTOSE",),
)
_OFFER = replace(
    samples.offer(),
    requested=replace(
        samples.offer().requested,
        quantity=Decimal(_QTY),
        unit=Unit.PCS,
        deliver_by=samples.DELIVERY_DATE,
    ),
)
_CONFIRMED = replace(
    samples.order(),
    placed_at=samples.NOW - timedelta(minutes=5),
    lines=(
        replace(
            samples.order().lines[0],
            qty=_QTY,
            unit_price=_UNIT_PRICE,
            line_total=_TOTAL,
        ),
    ),
    total_ex_vat=_TOTAL,
)
_DAY_ORDER = replace(
    _CONFIRMED,
    approved_by=None,
    lines=(
        replace(
            _CONFIRMED.lines[0],
            product_id="another-product",
            qty=1,
            unit_price=Decimal("301.00"),
            line_total=Decimal("301.00"),
        ),
    ),
    total_ex_vat=Decimal("301.00"),
)
_REJECTED = replace(
    samples.cart(state=CartState.REJECTED),
    lines=(
        replace(
            samples.cart().lines[0],
            qty=_QTY,
            unit_price=_UNIT_PRICE,
            line_total=_TOTAL,
        ),
    ),
    decided_at=samples.NOW - timedelta(minutes=5),
    reject_reason="We already have enough milk.",
)
_CONTEXT = PolicyContext(
    mandate=replace(
        samples.mandate(),
        max_auto_order_value=Decimal("500.00"),
        max_auto_value_per_delivery_date=Decimal("500.00"),
        max_line_value=None,
        required_attributes=("FREE_FROM_LACTOSE",),
        forbidden_allergens=("AN",),
        preferred_brands=("Valio",),
        can_auto_order=True,
    ),
    day_orders=(),
    recent_rejects=(),
    now=samples.NOW,
    baseline=build_baseline((_CONFIRMED,)),
    products={_PRODUCT_ID: _PRODUCT},
    offers={_OFFER.offer_id: _OFFER},
)
_ENGINE = PolicyEngine(
    (
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
    ),
)


def _lines(**changes):
    line = replace(_LINE, **changes)
    return (replace(line, line_total=line_total(line.qty, line.unit_price)),)


def _rules(**changes):
    return replace(_CONTEXT, mandate=replace(_CONTEXT.mandate, **changes))


def _product(**changes):
    return replace(_CONTEXT, products={_PRODUCT_ID: replace(_PRODUCT, **changes)})


def _request(**changes):
    offer = replace(_OFFER, requested=replace(_OFFER.requested, **changes))
    return replace(_CONTEXT, offers={offer.offer_id: offer})


@pytest.mark.parametrize(
    ("lines", "context", "decision", "reason_code", "line_id"),
    [
        pytest.param(
            _lines(),
            _CONTEXT,
            Decision.AUTO,
            None,
            None,
            id="AUTO-every-check-passes",
        ),
        pytest.param(
            _lines(),
            _rules(can_auto_order=False),
            Decision.HUMAN,
            ReasonCode.AUTO_ORDERS_OFF,
            None,
            id="HUMAN-AUTO_ORDERS_OFF",
        ),
        pytest.param(
            _lines(),
            replace(_CONTEXT, baseline={}),
            Decision.HUMAN,
            ReasonCode.NEW_PRODUCT,
            _PRODUCT_ID,
            id="HUMAN-NEW_PRODUCT",
        ),
        pytest.param(
            _lines(qty=41),
            _request(quantity=Decimal(41)),
            Decision.HUMAN,
            ReasonCode.QUANTITY_UNUSUAL,
            _PRODUCT_ID,
            id="HUMAN-QUANTITY_UNUSUAL",
        ),
        pytest.param(
            _lines(),
            _rules(max_auto_order_value=Decimal("199.99")),
            Decision.HUMAN,
            ReasonCode.OVER_AUTO_LIMIT,
            None,
            id="HUMAN-OVER_AUTO_LIMIT",
        ),
        pytest.param(
            _lines(),
            _rules(max_line_value=Decimal("199.99")),
            Decision.HUMAN,
            ReasonCode.OVER_LINE_LIMIT,
            _PRODUCT_ID,
            id="HUMAN-OVER_LINE_LIMIT",
        ),
        pytest.param(
            _lines(),
            replace(_CONTEXT, day_orders=(_DAY_ORDER,)),
            Decision.HUMAN,
            ReasonCode.OVER_DAILY_AUTO_LIMIT,
            None,
            id="HUMAN-OVER_DAILY_AUTO_LIMIT",
        ),
        pytest.param(
            _lines(),
            replace(_CONTEXT, day_orders=(_CONFIRMED,)),
            Decision.HUMAN,
            ReasonCode.DUPLICATE_ORDER,
            _PRODUCT_ID,
            id="HUMAN-DUPLICATE_ORDER",
        ),
        pytest.param(
            _lines(qty=23),
            _CONTEXT,
            Decision.HUMAN,
            ReasonCode.QUANTITY_OVER_REQUEST,
            _PRODUCT_ID,
            id="HUMAN-QUANTITY_OVER_REQUEST",
        ),
        pytest.param(
            _lines(),
            _product(brand="Arla"),
            Decision.HUMAN,
            ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,
            _PRODUCT_ID,
            id="HUMAN-SUBSTITUTE_OUTSIDE_PREFERENCE",
        ),
        pytest.param(
            _lines(substitute_for=_OFFER.lines[0].substitute_for),
            _CONTEXT,
            Decision.HUMAN,
            ReasonCode.SUBSTITUTE_FOR_REQUESTED,
            _PRODUCT_ID,
            id="HUMAN-SUBSTITUTE_FOR_REQUESTED",
        ),
        pytest.param(
            _lines(qty=10, available_qty=10),
            _CONTEXT,
            Decision.HUMAN,
            ReasonCode.PARTIAL_AVAILABILITY,
            _PRODUCT_ID,
            id="HUMAN-PARTIAL_AVAILABILITY-within-stock",
        ),
        pytest.param(
            _lines(available_qty=19),
            _CONTEXT,
            Decision.DENY,
            ReasonCode.PARTIAL_AVAILABILITY,
            _PRODUCT_ID,
            id="DENY-PARTIAL_AVAILABILITY-above-stock",
        ),
        pytest.param(
            _lines(stock_model=StockModel.TERMINAL),
            _CONTEXT,
            Decision.HUMAN,
            ReasonCode.STOCK_UNCONFIRMED,
            _PRODUCT_ID,
            id="HUMAN-STOCK_UNCONFIRMED-terminal",
        ),
        pytest.param(
            _lines(stock_model=None),
            _CONTEXT,
            Decision.HUMAN,
            ReasonCode.STOCK_UNCONFIRMED,
            _PRODUCT_ID,
            id="HUMAN-STOCK_UNCONFIRMED-missing-model",
        ),
        pytest.param(
            _lines(),
            _request(deliver_by=samples.DELIVERY_DATE - timedelta(days=1)),
            Decision.HUMAN,
            ReasonCode.DELIVERY_AFTER_DEADLINE,
            _PRODUCT_ID,
            id="HUMAN-DELIVERY_AFTER_DEADLINE",
        ),
        pytest.param(
            _lines(),
            _product(allergens=Allergens(AllergenStatus.UNKNOWN, ())),
            Decision.HUMAN,
            ReasonCode.ALLERGEN_UNKNOWN,
            _PRODUCT_ID,
            id="HUMAN-ALLERGEN_UNKNOWN",
        ),
        pytest.param(
            _lines(),
            replace(
                _product(allergens=Allergens(AllergenStatus.UNKNOWN, ())),
                mandate=replace(_CONTEXT.mandate, allergen_unknown_policy=Decision.DENY),
            ),
            Decision.DENY,
            ReasonCode.ALLERGEN_UNKNOWN,
            _PRODUCT_ID,
            id="DENY-ALLERGEN_UNKNOWN",
        ),
        pytest.param(
            _lines(),
            _product(
                allergens=Allergens(
                    AllergenStatus.KNOWN,
                    (),
                    {AllergenType.CONTAINS: ("AN",)},
                )
            ),
            Decision.DENY,
            ReasonCode.FORBIDDEN_ALLERGEN,
            _PRODUCT_ID,
            id="DENY-FORBIDDEN_ALLERGEN-contains",
        ),
        pytest.param(
            _lines(),
            _product(
                allergens=Allergens(
                    AllergenStatus.KNOWN,
                    (),
                    {AllergenType.MAY_CONTAIN: ("AN",)},
                )
            ),
            Decision.DENY,
            ReasonCode.FORBIDDEN_ALLERGEN,
            _PRODUCT_ID,
            id="DENY-FORBIDDEN_ALLERGEN-may-contain",
        ),
        pytest.param(
            _lines(),
            replace(_CONTEXT, recent_rejects=(_REJECTED,)),
            Decision.DENY,
            ReasonCode.PREVIOUSLY_REJECTED,
            None,
            id="DENY-PREVIOUSLY_REJECTED",
        ),
        pytest.param(
            _lines(closing_time=samples.NOW),
            _CONTEXT,
            Decision.DENY,
            ReasonCode.CUTOFF_PASSED,
            _PRODUCT_ID,
            id="DENY-CUTOFF_PASSED",
        ),
        pytest.param(
            _lines(),
            _product(attributes=()),
            Decision.DENY,
            ReasonCode.MISSING_ATTRIBUTE,
            _PRODUCT_ID,
            id="DENY-MISSING_ATTRIBUTE",
        ),
    ],
)
def test_policy_decision_table(lines, context, decision, reason_code, line_id):
    """Isolate each row so missing checks and unexpected extra reasons both fail the test."""
    result = _ENGINE.decide(lines, context)

    assert result.decision is decision
    if reason_code is None:
        assert result.reasons == ()
        return

    (reason,) = result.reasons
    assert reason.decision is decision
    assert reason.reason_code is reason_code
    assert reason.line_id == line_id
    assert reason.sentence.strip()
