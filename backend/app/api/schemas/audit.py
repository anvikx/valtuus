from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import AuditStep, Decision, FlowPhase, ReasonCode


class AuditRecord(BaseModel):
    record_id: str = Field(description="Record id.")
    cart_id: str | None = Field(description="Cart of the step. null before a cart exists.")
    request_id: str | None = Field(description="Id that links the steps of one buyer request.")
    step: AuditStep = Field(description="What the gateway did.")
    phase: FlowPhase | None = Field(description="Part of the flow the step belongs to.")
    actor: str = Field(description="Agent or user that made the call.")
    # The wire keeps the names input and output; Python code uses the _data names, which
    # do not shadow the builtin.
    input: dict[str, object] = Field(
        validation_alias="input_data",
        description="What the step received. No secrets.",
    )
    output: dict[str, object] = Field(
        validation_alias="output_data",
        description="What the step gave back.",
    )
    decision: Decision | None = Field(description="Decision of a policy step. null otherwise.")
    reason_codes: list[ReasonCode] = Field(description="Why the step ended as it did.")
    mandate_version: int | None = Field(description="Mandate version the step used.")
    sentence: str = Field(description="The step in one plain sentence.")
    created_at: datetime = Field(description="Time of the step.")


class AuditResponse(BaseModel):
    cart_id: str = Field(description="Cart id.")
    records: list[AuditRecord] = Field(description="Steps of the cart, oldest first.")
