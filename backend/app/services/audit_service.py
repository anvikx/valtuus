from collections.abc import Mapping, Sequence

from app.domain.audit import AuditRecord
from app.domain.enums import AuditStep, Decision, FlowPhase, ReasonCode
from app.services.ports.clock import Clock
from app.services.ports.repositories import AuditRepository


class AuditService:
    """The only writer of audit records. Any service may call it."""

    def __init__(self, records: AuditRepository, clock: Clock) -> None:
        self._records = records
        self._clock = clock

    def record(
        self,
        step: AuditStep,
        actor: str,
        sentence: str,
        cart_id: str | None = None,
        request_id: str | None = None,
        phase: FlowPhase | None = None,
        input_data: Mapping[str, object] | None = None,
        output_data: Mapping[str, object] | None = None,
        decision: Decision | None = None,
        reason_codes: Sequence[ReasonCode] = (),
        mandate_version: int | None = None,
    ) -> AuditRecord:
        raise NotImplementedError("AuditService.record")

    def for_cart(self, buyer_id: str, cart_id: str) -> Sequence[AuditRecord]:
        raise NotImplementedError("AuditService.for_cart")
