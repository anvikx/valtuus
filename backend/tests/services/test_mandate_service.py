import dataclasses
from decimal import Decimal

import pytest

from app.adapters.memory.repositories import (
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryUnitOfWork,
)
from app.domain.enums import Decision
from app.domain.mandate import Mandate
from app.services.audit_service import AuditService
from app.services.mandate_service import MandateService
from tests.adapters import samples

_PERSON_APPROVES = (
    "A person must approve: larger orders, partial stock, unconfirmed stock, another brand "
    "than preferred, a later delivery date, a repeated order, a pack size that gives much more "
    "than the request."
)
_NEVER = (
    "The agent can never: order a product with a forbidden allergen, order after the order "
    "deadline, change a price, approve its own cart, send a rejected cart again."
)


class _Clock:
    def now(self):
        return samples.NOW


def _summary(mandate: Mandate) -> tuple[str, ...]:
    unit_of_work = InMemoryUnitOfWork()
    audit = AuditService(
        InMemoryAuditRepository(),
        InMemoryCartRepository(),
        InMemoryOfferRepository(),
        _Clock(),
        unit_of_work,
    )
    service = MandateService(InMemoryMandateRepository(), _Clock(), audit, unit_of_work)
    return service.summary(mandate)


def _mandate(**changes: object) -> Mandate:
    plain = dataclasses.replace(
        samples.mandate(),
        max_auto_order_value=Decimal("500"),
        max_auto_value_per_delivery_date=Decimal("750.5"),
        preferred_brands=(),
        forbidden_allergens=(),
        allergen_unknown_policy=Decision.HUMAN,
    )
    return dataclasses.replace(plain, **changes)


def test_summary_states_the_limits_and_the_fixed_rules() -> None:
    """The main user reads these words before giving the agent money to spend."""
    assert _summary(_mandate()) == (
        "This agent may place orders up to 500.00 EUR per order and 750.50 EUR per delivery "
        "day with no approval (totals ex VAT).",
        _PERSON_APPROVES,
        _NEVER,
    )


def test_summary_names_the_preferred_brands() -> None:
    """After the main user picks Arla, the page must show that the agent knows it."""
    summary = _summary(_mandate(preferred_brands=("Arla", "Valio")))

    assert summary[1] == "Preferred brands: Arla, Valio."


def test_summary_names_the_forbidden_allergens() -> None:
    """A kitchen that serves a nut allergy must see that the agent will refuse nuts."""
    summary = _summary(_mandate(forbidden_allergens=("nuts", "fish")))

    assert summary[1] == (
        "Forbidden allergens: nuts, fish. "
        "A product with no allergen data needs a person's approval."
    )


@pytest.mark.parametrize(
    ("policy", "sentence"),
    [
        (Decision.DENY, "A product with no allergen data is never ordered."),
        (Decision.AUTO, "A product with no allergen data may be ordered with no approval."),
    ],
)
def test_summary_states_the_unknown_allergen_rule(policy: Decision, sentence: str) -> None:
    """With DENY the agent cannot even ask a person. With AUTO it orders unchecked food."""
    summary = _summary(_mandate(forbidden_allergens=("nuts",), allergen_unknown_policy=policy))

    assert summary[1] == f"Forbidden allergens: nuts. {sentence}"
