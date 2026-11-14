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
from app.domain.agent_key import User
from app.domain.audit import AuditRecord
from app.domain.enums import AuditStep, Decision, UserRole
from app.domain.errors import ConflictError, ForbiddenError, NotFoundError
from app.domain.mandate import Mandate
from app.services.audit_service import AuditService
from app.services.mandate_service import MandateChanges, MandateService
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


class _Records:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


_MAIN_USER = User(user_id="u_main", buyer_id=samples.BUYER_ID, role=UserRole.MAIN_USER)
_RAISED = Decimal("1500")


def _service(records: _Records | None = None) -> tuple[MandateService, InMemoryMandateRepository]:
    mandates = InMemoryMandateRepository()
    mandates.add(samples.mandate())
    unit_of_work = InMemoryUnitOfWork()
    audit = AuditService(
        records or _Records(),
        InMemoryCartRepository(),
        InMemoryOfferRepository(),
        _Clock(),
        unit_of_work,
    )
    return MandateService(mandates, _Clock(), audit, unit_of_work), mandates


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


def test_update_makes_the_next_version_with_the_change() -> None:
    """Checkout on a waiting cart reads the latest version, so the raise must land there."""
    service, mandates = _service()

    updated = service.update(_MAIN_USER, MandateChanges(max_auto_order_value=_RAISED))

    assert updated.version == 2
    assert updated.max_auto_order_value == _RAISED
    assert mandates.latest(samples.BUYER_ID) == updated


def test_update_keeps_the_fields_it_was_not_given() -> None:
    """Raising a limit must not drop the forbidden allergens of a kitchen."""
    service, _ = _service()
    before = samples.mandate()

    updated = service.update(_MAIN_USER, MandateChanges(max_auto_order_value=_RAISED))

    assert dataclasses.replace(updated, version=1, max_auto_order_value=_RAISED) == (
        dataclasses.replace(before, max_auto_order_value=_RAISED)
    )


def test_update_takes_every_editable_field() -> None:
    service, _ = _service()
    changes = MandateChanges(
        max_auto_order_value=_RAISED,
        max_auto_value_per_delivery_date=_RAISED,
        preferred_brands=("Arla",),
        forbidden_allergens=("fish",),
        allergen_unknown_policy=Decision.DENY,
    )

    updated = service.update(_MAIN_USER, changes)

    assert updated.max_auto_value_per_delivery_date == _RAISED
    assert updated.preferred_brands == ("Arla",)
    assert updated.forbidden_allergens == ("fish",)
    assert updated.allergen_unknown_policy is Decision.DENY


def test_update_with_no_change_makes_no_version() -> None:
    """A save with nothing changed must not show up as a mandate change in the audit."""
    records = _Records()
    service, _ = _service(records)

    same = service.update(_MAIN_USER, MandateChanges(preferred_brands=("Valio",)))

    assert same.version == 1
    assert records.records == []


def test_update_is_on_the_record() -> None:
    """Who raised the limit, and when, is what an auditor asks after an AUTO order."""
    records = _Records()
    service, _ = _service(records)

    service.update(_MAIN_USER, MandateChanges(max_auto_order_value=_RAISED))

    [record] = records.records
    assert record.step is AuditStep.MANDATE_CHANGED
    assert record.actor == _MAIN_USER.user_id
    assert record.buyer_id == samples.BUYER_ID
    assert record.mandate_version == 2
    assert record.input_data == {"max_auto_order_value": _RAISED}
    assert record.sentence == ("u_main changed the mandate to version 2: max_auto_order_value.")


def test_parallel_edit_is_a_conflict_not_a_lost_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two tabs both read version 1. The second save must not overwrite the first."""
    service, mandates = _service()
    mandates.add(samples.mandate(2))
    monkeypatch.setattr(mandates, "latest", lambda _: samples.mandate())

    with pytest.raises(ConflictError):
        service.update(_MAIN_USER, MandateChanges(max_auto_order_value=_RAISED))


def test_update_for_a_user_with_no_buyer_is_forbidden() -> None:
    """Staff act for no buyer, so they have no mandate to change."""
    service, _ = _service()
    staff = User(user_id="u_staff", buyer_id=None, role=UserRole.STAFF)

    with pytest.raises(ForbiddenError):
        service.update(staff, MandateChanges(max_auto_order_value=_RAISED))


def test_update_with_no_mandate_is_not_found() -> None:
    service, _ = _service()
    other = User(user_id="u_other", buyer_id="b_other", role=UserRole.MAIN_USER)

    with pytest.raises(NotFoundError):
        service.update(other, MandateChanges(max_auto_order_value=_RAISED))
