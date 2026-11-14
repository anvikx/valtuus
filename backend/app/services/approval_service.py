from dataclasses import replace

from app.domain.agent_key import User
from app.domain.cart import Cart
from app.domain.enums import AuditStep, CartState, FlowPhase
from app.domain.errors import ConflictError, ForbiddenError, InvalidRequestError
from app.domain.order import Order
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
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
        cart_service: CartService,
        orders: OrderService,
        mandates: MandateService,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._carts = carts
        self._cart_service = cart_service
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
        """REJECTED is final. Any other state is a 409, sent after the commit, so an expiry
        found on the way is kept."""
        reason = _reason_text(reason)
        with self._unit_of_work.transaction():
            # Lock first, so a parallel approve waits for this reject to finish.
            self._carts.get_locked(cart_id)
            # get_cart owns the buyer check and expiry on read.
            cart = self._cart_service.get_cart(_buyer_id(user), cart_id)
            if cart.state is CartState.PENDING_APPROVAL:
                return self._store_reject(user, cart_id, reason)

        raise ConflictError(
            f"Cart {cart_id} is {cart.state}, so it cannot be rejected.",
            "Only a cart that waits for approval can be rejected. Open the cart to see its state.",
        )

    def _store_reject(self, user: User, cart_id: str, reason: str) -> Cart:
        # The stored cart, not the get_cart view: that view adds the current decision,
        # which the store must not keep.
        cart = self._carts.get_locked(cart_id)
        rejected = replace(
            cart,
            state=CartState.REJECTED,
            decided_by=user.user_id,
            decided_at=self._clock.now(),
            reject_reason=reason,
        )
        self._carts.save(rejected)
        self._audit.record(
            AuditStep.APPROVAL,
            user.user_id,
            f"Rejected by {user.user_id}: {reason}",
            cart_id=cart_id,
            phase=FlowPhase.APPROVAL,
            input_data={"reason": reason},
            output_data={"state": rejected.state},
            mandate_version=cart.mandate_version,
        )
        return rejected


def _reason_text(reason: str) -> str:
    """The agent tells the buyer this text, so blank text is not a reason."""
    text = reason.strip()
    if not text:
        raise InvalidRequestError(
            "The reject reason is empty.",
            "Write why the cart is rejected.",
        )

    return text


def _buyer_id(user: User) -> str:
    if user.buyer_id is None:
        raise ForbiddenError(
            "This user acts for no buyer.",
            "Log in as the main user of the buyer.",
        )

    return user.buyer_id
