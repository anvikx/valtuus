from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.agent_key import User
from app.domain.constants import CURRENCY
from app.domain.enums import Decision
from app.domain.errors import NotFoundError
from app.domain.mandate import Mandate
from app.domain.money import round_money
from app.services.audit_service import AuditService
from app.services.ports.clock import Clock
from app.services.ports.repositories import MandateRepository
from app.services.ports.unit_of_work import UnitOfWork

_PERSON_APPROVES = (
    "A person must approve: larger orders, partial stock, unconfirmed stock, another brand "
    "than preferred, a later delivery date, a repeated order, a pack size that gives much more "
    "than the request."
)
_NEVER = (
    "The agent can never: order a product with a forbidden allergen, order after the order "
    "deadline, change a price, approve its own cart, send a rejected cart again."
)
_UNKNOWN_ALLERGENS = {
    Decision.HUMAN: "A product with no allergen data needs a person's approval.",
    Decision.DENY: "A product with no allergen data is never ordered.",
    Decision.AUTO: "A product with no allergen data may be ordered with no approval.",
}


@dataclass(frozen=True)
class MandateChanges:
    """The fields the main user may edit. None keeps the current value."""

    max_auto_order_value: Decimal | None = None
    max_auto_value_per_delivery_date: Decimal | None = None
    preferred_brands: tuple[str, ...] | None = None
    forbidden_allergens: tuple[str, ...] | None = None
    allergen_unknown_policy: Decision | None = None


class MandateService:
    def __init__(
        self,
        mandates: MandateRepository,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._mandates = mandates
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work

    def get(self, buyer_id: str) -> Mandate:
        mandate = self._mandates.latest(buyer_id)
        if mandate is None:
            raise NotFoundError(
                f"No mandate for buyer {buyer_id}.",
                "Ask the main user to set the mandate.",
            )

        return mandate

    def now(self) -> datetime:
        """The gateway time. The agent resolves "Monday" from it, not from its own clock."""
        return self._clock.now()

    def summary(self, mandate: Mandate) -> tuple[str, ...]:
        """Plain sentences from fixed templates. No LLM."""
        return (
            _limits_sentence(mandate),
            *_choice_sentences(mandate),
            _PERSON_APPROVES,
            _NEVER,
        )

    def update(self, user: User, changes: MandateChanges) -> Mandate:
        """Makes version + 1 and keeps the old one. Changes no cart and places no order."""
        raise NotImplementedError("MandateService.update")


def _limits_sentence(mandate: Mandate) -> str:
    order = _money_text(mandate.max_auto_order_value)
    day = _money_text(mandate.max_auto_value_per_delivery_date)
    return (
        f"This agent may place orders up to {order} per order and {day} per delivery day "
        "with no approval (totals ex VAT)."
    )


def _choice_sentences(mandate: Mandate) -> list[str]:
    """Only the choices the main user made, so an empty mandate stays short."""
    sentences = []
    if mandate.preferred_brands:
        sentences.append(f"Preferred brands: {', '.join(mandate.preferred_brands)}.")

    # The unknown allergen rule only acts when an allergen is forbidden.
    if mandate.forbidden_allergens:
        allergens = ", ".join(mandate.forbidden_allergens)
        unknown = _UNKNOWN_ALLERGENS[mandate.allergen_unknown_policy]
        sentences.append(f"Forbidden allergens: {allergens}. {unknown}")

    return sentences


def _money_text(amount: Decimal) -> str:
    return f"{round_money(amount)} {CURRENCY}"
