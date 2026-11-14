from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.agent_key import User
from app.domain.enums import Decision
from app.domain.mandate import Mandate
from app.services.audit_service import AuditService
from app.services.ports.clock import Clock
from app.services.ports.repositories import MandateRepository
from app.services.ports.unit_of_work import UnitOfWork


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
        raise NotImplementedError("MandateService.get")

    def now(self) -> datetime:
        """The gateway time. The agent resolves "Monday" from it, not from its own clock."""
        return self._clock.now()

    def summary(self, mandate: Mandate) -> tuple[str, ...]:
        """Plain sentences from fixed templates. No LLM."""
        raise NotImplementedError("MandateService.summary")

    def update(self, user: User, changes: MandateChanges) -> Mandate:
        """Makes version + 1 and keeps the old one. Changes no cart and places no order."""
        raise NotImplementedError("MandateService.update")
