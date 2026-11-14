from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from app.domain.enums import AuditStep, Decision, FlowPhase, ReasonCode

# The agent sends a request_id back on get_offers, so the wire checks it has this form.
REQUEST_ID_PATTERN = r"^r_[0-9a-f]{32}$"


def new_request_id() -> str:
    """Random, so an agent cannot guess another buyer's id. for_cart also checks the buyer."""
    return f"r_{uuid4().hex}"


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
    # A request id comes back from the agent, so a linked record joins a trail only when its
    # buyer is the cart's buyer. None only on records stored before the field existed.
    buyer_id: str | None = None
