from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.domain.enums import AuditStep, Decision, FlowPhase, ReasonCode


@dataclass(frozen=True)
class AuditRecord:
    """Append only. request_id links a search and its offers to the later cart."""

    record_id: str
    cart_id: str | None
    request_id: str | None
    step: AuditStep
    phase: FlowPhase | None
    actor: str
    input_data: Mapping[str, object]
    output_data: Mapping[str, object]
    decision: Decision | None
    reason_codes: tuple[ReasonCode, ...]
    mandate_version: int | None
    sentence: str
    created_at: datetime
