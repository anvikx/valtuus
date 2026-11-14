from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import AuditStep, Decision, FlowPhase, ReasonCode


class AuditRecord(BaseModel):
    record_id: str
    cart_id: str | None
    request_id: str | None
    step: AuditStep
    phase: FlowPhase | None
    actor: str
    # The wire keeps the names input and output; Python code uses the _data names, which
    # do not shadow the builtin.
    input: dict[str, object] = Field(validation_alias="input_data")
    output: dict[str, object] = Field(validation_alias="output_data")
    decision: Decision | None
    reason_codes: list[ReasonCode]
    mandate_version: int | None
    sentence: str
    created_at: datetime


class AuditResponse(BaseModel):
    cart_id: str
    records: list[AuditRecord]
