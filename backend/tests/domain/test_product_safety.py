import dataclasses

import pytest

from app.domain.cart import PricedLine
from app.domain.catalog import Allergens, Product
from app.domain.enums import AllergenStatus, AllergenType, Decision, ReasonCode, StockModel
from app.domain.mandate import Mandate
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.product_safety import ProductSafety
from tests.adapters import samples
from tests.fakes.offer_data import MILK_ID, product

_MILK = product()
_NO_DATA = dataclasses.replace(_MILK, allergens=Allergens(AllergenStatus.UNKNOWN, ()))
_MAY_CONTAIN_NUTS = dataclasses.replace(
    _MILK,
    allergens=Allergens(AllergenStatus.KNOWN, (), {AllergenType.MAY_CONTAIN: ("AN",)}),
)
_LACTOSE_FREE = dataclasses.replace(_MILK, attributes=("FREE_FROM_LACTOSE",))


def _mandate(**rules: object) -> Mandate:
    plain = {
        "required_attributes": (),
        "forbidden_allergens": (),
        "allergen_unknown_policy": Decision.HUMAN,
    }
    return dataclasses.replace(samples.mandate(), **{**plain, **rules})


def _line() -> PricedLine:
    return PricedLine(
        offer_id="of_1",
        product_id=MILK_ID,
        name="Milk 1 l",
        qty=10,
        unit_price=samples.SMALL_MONEY,
        line_total=samples.SMALL_MONEY,
        delivery_date=samples.DELIVERY_DATE,
        closing_time=samples.NOW,
        substitute_for=None,
        stock_model=StockModel.STOCK,
        available_qty=None,
        needed_qty=10,
    )


def _evaluate(mandate: Mandate, *products: Product) -> list[CheckResult]:
    context = PolicyContext(
        mandate=mandate,
        day_orders=(),
        recent_rejects=(),
        now=samples.NOW,
        products={item.product_id: item for item in products},
    )
    return ProductSafety().evaluate([_line()], context)


@pytest.mark.parametrize(
    ("mandate", "products", "expected"),
    [
        pytest.param(_mandate(), (_NO_DATA,), [], id="no-rules"),
        pytest.param(
            _mandate(forbidden_allergens=("AM",)),
            (_MILK,),
            [(Decision.DENY, ReasonCode.FORBIDDEN_ALLERGEN)],
            id="contains-forbidden",
        ),
        pytest.param(
            _mandate(forbidden_allergens=("AN",)),
            (_MAY_CONTAIN_NUTS,),
            [(Decision.DENY, ReasonCode.FORBIDDEN_ALLERGEN)],
            id="may-contain-counts-as-contains",
        ),
        pytest.param(
            _mandate(required_attributes=("FREE_FROM_LACTOSE",)),
            (_MILK,),
            [(Decision.DENY, ReasonCode.MISSING_ATTRIBUTE)],
            id="missing-attribute",
        ),
        pytest.param(
            _mandate(required_attributes=("FREE_FROM_LACTOSE",)),
            (_LACTOSE_FREE,),
            [],
            id="has-attribute",
        ),
        pytest.param(
            _mandate(forbidden_allergens=("AN",)),
            (_NO_DATA,),
            [(Decision.HUMAN, ReasonCode.ALLERGEN_UNKNOWN)],
            id="no-data-goes-to-a-person",
        ),
        pytest.param(
            _mandate(forbidden_allergens=("AN",), allergen_unknown_policy=Decision.DENY),
            (_NO_DATA,),
            [(Decision.DENY, ReasonCode.ALLERGEN_UNKNOWN)],
            id="no-data-is-refused",
        ),
        pytest.param(
            _mandate(forbidden_allergens=("AN",), allergen_unknown_policy=Decision.AUTO),
            (_NO_DATA,),
            [],
            id="no-data-is-allowed",
        ),
        pytest.param(
            _mandate(allergen_unknown_policy=Decision.DENY),
            (_NO_DATA,),
            [],
            id="no-data-with-nothing-forbidden",
        ),
        pytest.param(
            _mandate(forbidden_allergens=("AN",)),
            (),
            [(Decision.HUMAN, ReasonCode.ALLERGEN_UNKNOWN)],
            id="not-in-catalog-has-no-data",
        ),
        pytest.param(
            _mandate(required_attributes=("FREE_FROM_LACTOSE",)),
            (),
            [(Decision.DENY, ReasonCode.MISSING_ATTRIBUTE)],
            id="not-in-catalog-has-no-attributes",
        ),
    ],
)
def test_cart_line_follows_the_product_rules(mandate, products, expected):
    """An agent can ask offers for any product id, so the cart is where the rules must hold."""
    results = _evaluate(mandate, *products)

    assert [(result.decision, result.reason_code) for result in results] == expected


def test_every_broken_rule_is_named_on_the_line():
    """The person sees all problems at once, not one per approval round."""
    mandate = _mandate(forbidden_allergens=("AM",), required_attributes=("FREE_FROM_LACTOSE",))

    assert _evaluate(mandate, _MILK) == [
        CheckResult(
            decision=Decision.DENY,
            reason_code=ReasonCode.FORBIDDEN_ALLERGEN,
            sentence="This product contains an allergen the main user forbids.",
            line_id=MILK_ID,
        ),
        CheckResult(
            decision=Decision.DENY,
            reason_code=ReasonCode.MISSING_ATTRIBUTE,
            sentence="This product is not FREE_FROM_LACTOSE, which the main user requires.",
            line_id=MILK_ID,
        ),
    ]


def test_missing_allergen_data_sentence():
    mandate = _mandate(forbidden_allergens=("AN",))

    (result,) = _evaluate(mandate, _NO_DATA)

    assert result.sentence == "The allergens of this product are not known."


def test_each_missing_attribute_has_its_own_sentence():
    mandate = _mandate(required_attributes=("FREE_FROM_LACTOSE", "VEGAN"))

    sentences = [result.sentence for result in _evaluate(mandate, _MILK)]

    assert sentences == [
        "This product is not FREE_FROM_LACTOSE, which the main user requires.",
        "This product is not VEGAN, which the main user requires.",
    ]
