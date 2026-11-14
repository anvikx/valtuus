from app.domain.agent_key import AgentKey, User
from app.domain.cart import Cart
from app.domain.order import Order
from app.services.audit_service import AuditService
from app.services.mandate_service import MandateService
from app.services.ports.clock import Clock
from app.services.ports.price_source import PriceSource
from app.services.ports.repositories import (
    CartRepository,
    IdempotencyRepository,
    OrderRepository,
)
from app.services.ports.signer import Signer
from app.services.ports.unit_of_work import UnitOfWork


class OrderService:
    def __init__(
        self,
        carts: CartRepository,
        orders: OrderRepository,
        idempotency: IdempotencyRepository,
        mandates: MandateService,
        prices: PriceSource,
        signer: Signer,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._carts = carts
        self._orders = orders
        self._idempotency = idempotency
        self._mandates = mandates
        self._prices = prices
        self._signer = signer
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work

    def checkout(self, agent: AgentKey, cart_id: str, idempotency_key: str) -> Order | Cart:
        """An Order, or the cart in its new state (HUMAN, DENY, EXPIRED), already committed."""
        raise NotImplementedError("OrderService.checkout")

    def place(self, cart: Cart, approved_by: User | None) -> Order | Cart:
        """The one path to an order, for checkout and approve: price check, sign, store."""
        raise NotImplementedError("OrderService.place")

    def get_order(self, buyer_id: str, order_id: str) -> Order:
        raise NotImplementedError("OrderService.get_order")
