from app.domain.agent_key import User
from app.domain.cart import Cart
from app.domain.order import Order
from app.services.audit_service import AuditService
from app.services.mandate_service import MandateService
from app.services.order_service import OrderService
from app.services.ports.clock import Clock
from app.services.ports.repositories import CartRepository
from app.services.ports.unit_of_work import UnitOfWork


class ApprovalService:
    """Approve and reject. Only a main user session reaches it, never an agent key."""

    def __init__(
        self,
        carts: CartRepository,
        orders: OrderService,
        mandates: MandateService,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._carts = carts
        self._orders = orders
        self._mandates = mandates
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work

    def approve(self, user: User, cart_id: str) -> Order | Cart:
        """An Order, or the cart in its new state (EXPIRED, DENIED). A second tap gets the same
        Order."""
        raise NotImplementedError("ApprovalService.approve")

    def reject(self, user: User, cart_id: str, reason: str) -> Cart:
        raise NotImplementedError("ApprovalService.reject")
