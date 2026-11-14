from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from uuid import uuid4

from app.domain.enums import AuditStep, Decision, FlowPhase, ReasonCode
from app.domain.reason_text import money_text

# The agent sends a request_id back on get_offers, so the wire checks it has this form.
REQUEST_ID_PATTERN = r"^r_[0-9a-f]{32}$"

# The run page groups records by phase. A step not here (a mandate change, a revoked key) is in
# no run, so its phase is None.
AUDIT_PHASE = MappingProxyType(
    {
        AuditStep.SEARCH: FlowPhase.LOOKUP,
        AuditStep.OFFER: FlowPhase.LOOKUP,
        AuditStep.CART: FlowPhase.ORDER,
        AuditStep.POLICY: FlowPhase.APPROVAL,
        AuditStep.APPROVAL: FlowPhase.APPROVAL,
        AuditStep.ORDER: FlowPhase.APPROVAL,
    }
)

_POLICY_OUTCOME = MappingProxyType(
    {
        Decision.AUTO: "The policy let the agent order",
        Decision.HUMAN: "The policy sent the cart to a person",
        Decision.DENY: "The policy refused the cart",
    }
)
_WITHIN_MANDATE = "the cart is within the mandate."


def new_request_id() -> str:
    """Random, so an agent cannot guess another buyer's id. for_cart also checks the buyer."""
    return f"r_{uuid4().hex}"


def audit_phase(step: AuditStep, cart_id: str | None) -> FlowPhase | None:
    """A refused call on a cart is part of its approval. Without a cart it is in no run."""
    if step is AuditStep.REFUSED and cart_id is not None:
        return FlowPhase.APPROVAL

    return AUDIT_PHASE.get(step)


def cart_sentence(product_ids: Iterable[str], total_ex_vat: Decimal) -> str:
    # The prices come from the stored offer, never from the agent, so the total is fixed.
    products = ", ".join(product_ids)
    total = money_text(total_ex_vat)
    return f"The agent built a cart with {products}. {total} ex VAT, fixed price."


def policy_sentence(decision: Decision, reason_sentences: Iterable[str]) -> str:
    reasons = " ".join(reason_sentences) or _WITHIN_MANDATE
    return f"{_POLICY_OUTCOME[decision]}: {reasons}"


def order_sentence(total_ex_vat: Decimal) -> str:
    return f"The order was committed at the signed price: {money_text(total_ex_vat)} ex VAT."


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
