from collections.abc import Sequence

from app.domain.agent_key import AgentKey
from app.domain.cart import Cart, CartDraft
from app.services.audit_service import AuditService
from app.services.mandate_service import MandateService
from app.services.ports.clock import Clock
from app.services.ports.repositories import (
    CartRepository,
    IdempotencyRepository,
    OfferRepository,
    OrderRepository,
)
from app.services.ports.unit_of_work import UnitOfWork


class CartService:
    """Builds a cart from stored offer lines and runs the policy. Owns expiry on read."""

    def __init__(
        self,
        offers: OfferRepository,
        carts: CartRepository,
        orders: OrderRepository,
        idempotency: IdempotencyRepository,
        mandates: MandateService,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._offers = offers
        self._carts = carts
        self._orders = orders
        self._idempotency = idempotency
        self._mandates = mandates
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work

    def create_cart(self, agent: AgentKey, draft: CartDraft, idempotency_key: str) -> Cart:
        raise NotImplementedError("CartService.create_cart")

    def get_cart(self, buyer_id: str, cart_id: str) -> Cart:
        """Expiry on read first, then current_decision by the current mandate."""
        raise NotImplementedError("CartService.get_cart")

    def list_for_inbox(self, buyer_id: str) -> Sequence[Cart]:
        raise NotImplementedError("CartService.list_for_inbox")
