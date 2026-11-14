from collections.abc import Mapping, Sequence
from uuid import uuid4

from app.domain.audit import AuditRecord
from app.domain.enums import AuditStep, Decision, FlowPhase, ReasonCode
from app.services.ports.clock import Clock
from app.services.ports.repositories import AuditRepository
from app.services.ports.unit_of_work import UnitOfWork


class AuditService:
    """The only writer of audit records. Any service may call it."""

    def __init__(self, records: AuditRepository, clock: Clock, unit_of_work: UnitOfWork) -> None:
        self._records = records
        self._clock = clock
        self._unit_of_work = unit_of_work

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
        record = AuditRecord(
            record_id=f"a_{uuid4().hex}",
            cart_id=cart_id,
            request_id=request_id,
            step=step,
            phase=phase,
            actor=actor,
            input_data=input_data or {},
            output_data=output_data or {},
            decision=decision,
            reason_codes=tuple(reason_codes),
            mandate_version=mandate_version,
            sentence=sentence,
            created_at=self._clock.now(),
        )
        self._records.append(record)
        return record

    def record_refusal(
        self,
        actor: str,
        sentence: str,
        reason: ReasonCode,
        input_data: Mapping[str, object],
    ) -> AuditRecord:
        """A refused call changes no state, so its record needs a transaction of its own."""
        with self._unit_of_work.transaction():
            return self.record(
                AuditStep.REFUSED,
                actor,
                sentence,
                input_data=input_data,
                reason_codes=(reason,),
            )

    def for_cart(self, buyer_id: str, cart_id: str) -> Sequence[AuditRecord]:
        raise NotImplementedError("AuditService.for_cart")
