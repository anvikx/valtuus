from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import ServicesDep, require_scope
from app.api.results import audit_response
from app.api.schemas.audit import AuditResponse
from app.domain.agent_key import AgentKey
from app.domain.enums import AgentScope

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("/{cart_id}")
def get_audit(
    cart_id: str,
    agent: Annotated[AgentKey, Depends(require_scope(AgentScope.AUDIT_READ))],
    services: ServicesDep,
) -> AuditResponse:
    return audit_response(cart_id, services.audit.for_cart(agent.buyer_id, cart_id))
