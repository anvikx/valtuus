from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from app.domain.cart import PricedLine
from app.domain.catalog import Allergens, ContentPerSalesUnit
from app.domain.enums import AllergenStatus, AllergenType, Decision, EnvelopeMode, ReasonCode, Unit
from app.domain.money import line_total
from app.domain.policy.baseline import build_baseline
from app.domain.policy.check import PolicyContext
from app.domain.policy.checks.cutoff import Cutoff
from app.domain.policy.checks.envelope import KnownProduct, Quantity
from app.domain.policy.checks.line_limit import LineLimit
from app.domain.policy.checks.product_rules import Allergen, Brand, RequiredAttributes, Substitute
from app.domain.policy.checks.request_rules import Delivery, RequestQuantity
from app.domain.policy.engine import PolicyEngine
from app.domain.policy.order_limit import OrderLimit
from tests.adapters import samples
from tests.fakes.offer_data import product

_PRODUCT_ID = samples.offer().lines[0].product_id
_PRICE = Decimal("1.00")
_ENGINE = PolicyEngine((KnownProduct(), Quantity(), OrderLimit(), Allergen()))


def _lines(qty=40, **changes):
    line = PricedLine(
        offer_id="of_1",
        product_id=_PRODUCT_ID,
        name="Oat milk",
        qty=qty,
        unit_price=_PRICE,
        line_total=line_total(qty, _PRICE),
        delivery_date=samples.DELIVERY_DATE,
        closing_time=samples.NOW + timedelta(days=1),
        substitute_for=None,
        stock_model=samples.offer().lines[0].stock_model,
        available_qty=None,
        needed_qty=qty,
    )
    return (replace(line, **changes),)


def _confirmed(qty=20, **changes):
    line = replace(samples.order().lines[0], qty=qty)
    return replace(samples.order(), lines=(line,), **changes)


def _context(*orders, product_changes=None, requested=None, **rules):
    mandate = replace(
        samples.mandate(),
        max_auto_order_value=Decimal("500"),
        max_auto_value_per_delivery_date=Decimal("500"),
        max_line_value=None,
        required_attributes=(),
        forbidden_allergens=(),
        preferred_brands=(),
    )
    item = replace(product(_PRODUCT_ID), **(product_changes or {}))
    offer = samples.offer()
    if requested is not None:
        offer = replace(offer, requested=replace(offer.requested, **requested))
    return PolicyContext(
        mandate=replace(mandate, **rules),
        day_orders=(),
        recent_rejects=(),
        now=samples.NOW,
        baseline=build_baseline(orders),
        products={_PRODUCT_ID: item},
        offers={offer.offer_id: offer},
    )


@pytest.mark.parametrize(
    ("qty", "orders", "codes"),
    [
        (300, (), (ReasonCode.NEW_PRODUCT,)),
        (40, (_confirmed(),), ()),
        (41, (_confirmed(),), (ReasonCode.QUANTITY_UNUSUAL,)),
        (80, (_confirmed(), _confirmed(40, approved_by=None)), (ReasonCode.QUANTITY_UNUSUAL,)),
        (501, (), (ReasonCode.NEW_PRODUCT, ReasonCode.OVER_AUTO_LIMIT)),
    ],
)
def test_confirmed_envelope(qty, orders, codes):
    """Automatic orders cannot increase the quantity a person has authorized."""
    result = _ENGINE.decide(_lines(qty), _context(*orders))

    assert tuple(reason.reason_code for reason in result.reasons) == codes
    assert result.decision is (Decision.HUMAN if codes else Decision.AUTO)


def test_quantity_reason_names_the_baseline_and_new_value():
    (reason,) = _ENGINE.decide(_lines(41), _context(_confirmed())).reasons

    assert "41" in reason.sentence
    assert "20" in reason.sentence
    assert reason.line_id == _PRODUCT_ID


def test_baseline_uses_all_history_and_latest_confirmed_price():
    older = _confirmed(200, placed_at=samples.NOW - timedelta(days=1000))
    recent = replace(_confirmed(), lines=(replace(_confirmed().lines[0], unit_price=_PRICE),))

    baseline = build_baseline((recent, older, _confirmed(1000, approved_by=None)))[_PRODUCT_ID]

    assert baseline.confirmed_count == 2
    assert baseline.max_confirmed_quantity == 200
    assert baseline.last_confirmed_unit_price == _PRICE
    assert baseline.last_confirmed_at == recent.placed_at


def test_envelope_off_leaves_hard_limits_active():
    context = _context(envelope_mode=EnvelopeMode.OFF)

    assert _ENGINE.decide(_lines(), context).decision is Decision.AUTO
    result = _ENGINE.decide(_lines(501), context)
    assert tuple(reason.reason_code for reason in result.reasons) == (ReasonCode.OVER_AUTO_LIMIT,)


def test_quantity_factor_is_read_from_the_current_mandate():
    context = _context(_confirmed(), quantity_factor=Decimal("3"))

    assert _ENGINE.decide(_lines(60), context).decision is Decision.AUTO
    assert _ENGINE.decide(_lines(61), context).decision is Decision.HUMAN


def test_known_product_with_forbidden_allergen_is_denied():
    allergens = Allergens(AllergenStatus.KNOWN, (), {AllergenType.MAY_CONTAIN: ("nuts",)})
    context = _context(
        _confirmed(), product_changes={"allergens": allergens}, forbidden_allergens=("nuts",)
    )

    result = _ENGINE.decide(_lines(), context)

    assert result.decision is Decision.DENY
    assert result.reasons[0].reason_code is ReasonCode.FORBIDDEN_ALLERGEN


def test_all_reasons_survive_a_deny():
    allergens = Allergens(AllergenStatus.KNOWN, (), {AllergenType.CONTAINS: ("nuts",)})
    context = _context(product_changes={"allergens": allergens}, forbidden_allergens=("nuts",))

    result = _ENGINE.decide(_lines(501), context)

    assert result.decision is Decision.DENY
    assert tuple(reason.reason_code for reason in result.reasons) == (
        ReasonCode.NEW_PRODUCT,
        ReasonCode.OVER_AUTO_LIMIT,
        ReasonCode.FORBIDDEN_ALLERGEN,
    )


@pytest.mark.parametrize("decision", [Decision.HUMAN, Decision.DENY, Decision.AUTO])
def test_unknown_allergens_follow_the_mandate(decision):
    allergens = Allergens(AllergenStatus.UNKNOWN, ())
    context = _context(
        product_changes={"allergens": allergens},
        forbidden_allergens=("nuts",),
        allergen_unknown_policy=decision,
    )

    results = Allergen().evaluate(_lines(), context)

    assert [reason.decision for reason in results] == (
        [] if decision is Decision.AUTO else [decision]
    )


def test_missing_allergens_are_never_assumed_safe():
    context = replace(_context(forbidden_allergens=("nuts",)), products={}, offers={})

    (result,) = Allergen().evaluate(_lines(), context)

    assert result.reason_code is ReasonCode.ALLERGEN_UNKNOWN
    assert result.decision is Decision.HUMAN


def test_offer_allergens_apply_without_catalog_data():
    context = replace(_context(forbidden_allergens=("oats",)), products={})

    (result,) = Allergen().evaluate(_lines(), context)

    assert result.reason_code is ReasonCode.FORBIDDEN_ALLERGEN


def test_same_input_produces_the_same_result():
    lines, context = _lines(501), _context(_confirmed())

    assert _ENGINE.decide(lines, context) == _ENGINE.decide(lines, context)


@pytest.mark.parametrize(
    ("check", "line_changes", "product_changes", "rules", "code", "decision"),
    [
        (
            LineLimit(),
            {},
            {},
            {"max_line_value": Decimal("39")},
            ReasonCode.OVER_LINE_LIMIT,
            Decision.HUMAN,
        ),
        (
            Brand(),
            {},
            {"brand": "Arla"},
            {"preferred_brands": ("Valio",)},
            ReasonCode.SUBSTITUTE_OUTSIDE_PREFERENCE,
            Decision.HUMAN,
        ),
        (
            Substitute(),
            {"substitute_for": samples.offer().lines[0].substitute_for},
            {},
            {},
            ReasonCode.SUBSTITUTE_FOR_REQUESTED,
            Decision.HUMAN,
        ),
        (
            RequiredAttributes(),
            {},
            {"attributes": ()},
            {"required_attributes": ("LOW_FAT",)},
            ReasonCode.MISSING_ATTRIBUTE,
            Decision.DENY,
        ),
        (Cutoff(), {"closing_time": samples.NOW}, {}, {}, ReasonCode.CUTOFF_PASSED, Decision.DENY),
    ],
)
def test_cart_rule_failure(check, line_changes, product_changes, rules, code, decision):
    context = _context(product_changes=product_changes, **rules)

    (result,) = check.evaluate(_lines(**line_changes), context)

    assert result.reason_code is code
    assert result.decision is decision
    assert result.line_id == _PRODUCT_ID


@pytest.mark.parametrize(
    ("check", "line_changes", "product_changes", "rules"),
    [
        (LineLimit(), {}, {}, {"max_line_value": Decimal("40")}),
        (LineLimit(), {}, {}, {"max_line_value": None}),
        (Brand(), {}, {"brand": "VALIO"}, {"preferred_brands": ("Valio",)}),
        (Brand(), {}, {"brand": "Arla"}, {"preferred_brands": ()}),
        (Substitute(), {}, {}, {}),
        (
            RequiredAttributes(),
            {},
            {"attributes": ("LOW_FAT",)},
            {"required_attributes": ("LOW_FAT",)},
        ),
        (Cutoff(), {}, {}, {}),
    ],
)
def test_cart_rule_pass(check, line_changes, product_changes, rules):
    context = _context(product_changes=product_changes, **rules)

    assert check.evaluate(_lines(**line_changes), context) == []


@pytest.mark.parametrize(
    ("days_late", "expected"), [(0, []), (1, [ReasonCode.DELIVERY_AFTER_DEADLINE])]
)
def test_delivery_deadline(days_late, expected):
    context = _context(requested={"deliver_by": samples.DELIVERY_DATE - timedelta(days=days_late)})

    results = Delivery().evaluate(_lines(), context)

    assert [result.reason_code for result in results] == expected


@pytest.mark.parametrize(("qty", "expected"), [(22, []), (23, [ReasonCode.QUANTITY_OVER_REQUEST])])
def test_request_excess_boundary(qty, expected):
    context = _context(
        requested={"quantity": Decimal("20"), "unit": Unit.PCS},
        product_changes={"content_per_sales_unit": ContentPerSalesUnit(Decimal(1), Unit.PCS)},
    )

    results = RequestQuantity().evaluate(_lines(qty), context)

    assert [result.reason_code for result in results] == expected


def test_pack_excess_uses_content_units():
    context = _context(
        requested={"quantity": Decimal("12"), "unit": Unit.L},
        product_changes={"content_per_sales_unit": ContentPerSalesUnit(Decimal(5), Unit.L)},
    )

    (result,) = RequestQuantity().evaluate(_lines(3), context)

    assert result.reason_code is ReasonCode.QUANTITY_OVER_REQUEST
    assert "15" in result.sentence and "12" in result.sentence


def test_missing_size_cannot_silently_pass_request_quantity():
    context = _context(
        requested={"quantity": Decimal("12"), "unit": Unit.L},
        product_changes={"content_per_sales_unit": None},
    )

    (result,) = RequestQuantity().evaluate(_lines(3), context)

    assert result.decision is Decision.DENY
    assert result.reason_code is ReasonCode.NO_CONTENT_DATA
