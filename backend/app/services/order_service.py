from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from itertools import groupby
from uuid import uuid4

from app.domain.agent_key import AgentKey, User
from app.domain.audit import order_sentence, policy_sentence
from app.domain.cart import OPEN_STATES, STATE_BY_DECISION, Cart, CartLine
from app.domain.enums import AuditStep, CartState, Decision, ReasonCode
from app.domain.errors import ConflictError, NotFoundError
from app.domain.fresh_check import line_holds
from app.domain.idempotency import IdempotencyRecord, request_hash
from app.domain.mandate import Mandate
from app.domain.offer import Availability, Price
from app.domain.order import Order, OrderLine
from app.domain.policy.engine import PolicyResult
from app.domain.reason_text import reason_sentence
from app.services.audit_service import AuditService
from app.services.cart_service import CartService
from app.services.offer_service import ISSUER
from app.services.ports.clock import Clock
from app.services.ports.price_source import PriceSource
from app.services.ports.repositories import (
    CartRepository,
    IdempotencyRepository,
    OfferRepository,
    OrderRepository,
)
from app.services.ports.signer import Signer
from app.services.ports.unit_of_work import UnitOfWork

_OPERATION = "checkout"
_GATEWAY_ACTOR = "gateway"


@dataclass(frozen=True)
class _FreshData:
    """Price and stock read again for a cart whose offer snapshot ran out."""

    prices: Mapping[str, Price]
    stock: Mapping[str, Availability]

    def changed(self, cart: Cart) -> bool:
        return not all(
            line_holds(line, self.prices.get(line.product_id), self.stock.get(line.product_id))
            for line in cart.lines
        )


class OrderService:
    """Places orders. The cart lock, the policy rerun and the insert share one transaction."""

    def __init__(
        self,
        cart_service: CartService,
        carts: CartRepository,
        orders: OrderRepository,
        offers: OfferRepository,
        idempotency: IdempotencyRepository,
        prices: PriceSource,
        signer: Signer,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._cart_service = cart_service
        self._carts = carts
        self._orders = orders
        self._offers = offers
        self._idempotency = idempotency
        self._prices = prices
        self._signer = signer
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work

    def checkout(self, agent: AgentKey, cart_id: str, idempotency_key: str) -> Order | Cart:
        """An Order, or the cart in its new state (HUMAN, DENY, EXPIRED), already committed."""
        # get_cart answers 404 for another buyer's cart and runs expiry on read. It goes before
        # the key read: a parallel call that commits between the two then shows as a used key,
        # not as an ORDERED cart with no order for this call.
        cart = self._cart_service.get_cart(agent.buyer_id, cart_id)
        fingerprint = request_hash(_OPERATION, {"cart_id": cart_id})
        used = self._idempotency.get(agent.buyer_id, idempotency_key)
        if used is not None:
            return self._replay(used, fingerprint)

        if cart.state not in OPEN_STATES:
            return cart

        # The key points at the cart, not the order: by_cart then finds the one order of the
        # cart, also when a parallel call placed it.
        claim = IdempotencyRecord(agent.buyer_id, idempotency_key, fingerprint, cart_id)
        return self._place(cart, None, claim)

    def place(self, cart: Cart, approved_by: User | None) -> Order | Cart:
        """The one path to an order, for checkout and approve: price check, sign, store."""
        return self._place(cart, approved_by, None)

    def get_order(self, buyer_id: str, order_id: str) -> Order:
        order = self._orders.get(order_id)
        # One answer for both cases, so an agent cannot probe other buyers' order ids.
        if order is None or order.buyer_id != buyer_id:
            raise NotFoundError(f"Order {order_id} was not found.", "Check the order id.")

        return order

    def _replay(self, used: IdempotencyRecord, fingerprint: str) -> Order | Cart:
        if used.request_hash != fingerprint:
            raise ConflictError(
                f"Idempotency-Key {used.key} was used for another request.",
                "Use a new Idempotency-Key for a new checkout.",
            )

        order = self._orders.by_cart(used.result_id)
        if order is None:
            return self._cart_service.get_cart(used.buyer_id, used.result_id)

        return order

    def _place(
        self,
        cart: Cart,
        approved_by: User | None,
        claim: IdempotencyRecord | None,
    ) -> Order | Cart:
        # Valio Aimo is read before the transaction: no remote call while the cart is locked.
        fresh = self._fresh_data(cart)
        with self._unit_of_work.transaction():
            # The day lock goes first, so no other checkout places an AUTO order for these dates
            # between the policy's read of the day's orders and this order. Approve skips it:
            # an approved order does not count for the daily AUTO limit.
            if approved_by is None:
                self._orders.lock_days(cart.buyer_id, (line.delivery_date for line in cart.lines))
            locked = self._cart_service.locked_cart(cart.cart_id)
            # A call with the same key may have placed the order while this one waited on the lock.
            used = None if claim is None else self._idempotency.get(claim.buyer_id, claim.key)
            if used is not None:
                return self._replay(used, claim.request_hash)

            if locked.state not in OPEN_STATES:
                return locked

            now = self._clock.now()
            mandate, result = self._cart_service.current_policy(locked, now)
            if not _allows(result.decision, approved_by):
                # A person's yes that ends in DENY must still show in the timeline.
                self._record_approval(locked, approved_by, mandate.version)
                return self._hold(locked, mandate, result)

            if fresh is not None and fresh.changed(locked):
                self._record_approval(locked, approved_by, mandate.version)
                return self._expire_changed(locked)

            if claim is not None:
                self._claim(claim)
            order = self._signed(self._order(locked, approved_by, mandate, now))
            self._store(locked, order)
            self._record_order(locked, order, result, approved_by)

        return order

    def _fresh_data(self, cart: Cart) -> _FreshData | None:
        if self._clock.now() < cart.valid_until:
            return None

        prices: dict[str, Price] = {}
        stock: dict[str, Availability] = {}
        by_date = sorted(cart.lines, key=lambda line: line.delivery_date)
        for day, lines in groupby(by_date, key=lambda line: line.delivery_date):
            ids = [line.product_id for line in lines]
            prices.update(self._prices.prices(ids, day))
            stock.update(self._prices.availability(ids, day).items)

        return _FreshData(prices, stock)

    def _hold(self, cart: Cart, mandate: Mandate, result: PolicyResult) -> Cart:
        """HUMAN or DENY now. Stored, so the 409 the door builds is what get_cart shows."""
        codes = tuple(reason.reason_code for reason in result.reasons)
        held = replace(
            cart,
            state=STATE_BY_DECISION[result.decision],
            decision=result.decision,
            reason_codes=codes,
            reason_sentences=tuple(reason.sentence for reason in result.reasons),
            current_decision=result.decision,
            current_reason_codes=codes,
            mandate_version=mandate.version,
        )
        self._carts.save(held)
        self._audit.record(
            AuditStep.POLICY,
            _GATEWAY_ACTOR,
            policy_sentence(result.decision, held.reason_sentences),
            cart_id=cart.cart_id,
            input_data={"state": cart.state},
            output_data={"state": held.state},
            decision=result.decision,
            reason_codes=codes,
            mandate_version=mandate.version,
        )
        return held

    def _expire_changed(self, cart: Cart) -> Cart:
        sentence = reason_sentence(ReasonCode.PRICE_OR_STOCK_CHANGED)
        expired = replace(
            cart,
            state=CartState.EXPIRED,
            reason_codes=(ReasonCode.PRICE_OR_STOCK_CHANGED,),
            reason_sentences=(sentence,),
        )
        self._carts.save(expired)
        self._audit.record(
            AuditStep.CART,
            _GATEWAY_ACTOR,
            sentence,
            cart_id=cart.cart_id,
            input_data={"state": cart.state},
            output_data={"state": expired.state},
            reason_codes=expired.reason_codes,
            mandate_version=cart.mandate_version,
        )
        return expired

    def _claim(self, claim: IdempotencyRecord) -> None:
        """The first write of the order path, so a lost race stores nothing."""
        try:
            self._idempotency.add(claim)
        except ValueError as error:
            raise ConflictError(
                f"Another call with Idempotency-Key {claim.key} is placing this order.",
                "Retry with the same Idempotency-Key to get that order.",
            ) from error

    def _order(
        self,
        cart: Cart,
        approved_by: User | None,
        mandate: Mandate,
        now: datetime,
    ) -> Order:
        return Order(
            order_id=f"ord_{uuid4().hex}",
            cart_id=cart.cart_id,
            buyer_id=cart.buyer_id,
            lines=tuple(_order_line(line, self._gtin(line)) for line in cart.lines),
            total_ex_vat=cart.total_ex_vat,
            currency=cart.currency,
            placed_at=now,
            placed_by=f"{cart.agent_name} (agent)",
            approved_by=None if approved_by is None else approved_by.user_id,
            offer_ids=tuple(dict.fromkeys(line.offer_id for line in cart.lines)),
            mandate_version=mandate.version,
            issuer=ISSUER,
            signature=None,
        )

    def _gtin(self, line: CartLine) -> str | None:
        offer = self._offers.get(line.offer_id)
        if offer is None:
            # A cart is only made from a stored offer, and offers are never deleted.
            raise RuntimeError(f"offer {line.offer_id} of a cart is gone")

        return next(
            (item.gtin for item in offer.lines if item.product_id == line.product_id),
            None,
        )

    def _signed(self, order: Order) -> Order:
        # buyer_id is on the order confirmation, so unlike an offer it stays in the payload.
        body = asdict(order)
        del body["signature"]
        return replace(order, signature=self._signer.sign(body))

    def _store(self, cart: Cart, order: Order) -> None:
        try:
            self._orders.add(order)
        except ValueError as error:
            # The cart lock makes this unreachable on Postgres; the memory store has no lock.
            raise ConflictError(
                f"Cart {cart.cart_id} already has an order.",
                "Read the cart to get its order id.",
            ) from error

        approved_at = None if order.approved_by is None else order.placed_at
        self._carts.save(
            replace(
                cart,
                state=CartState.ORDERED,
                order_id=order.order_id,
                decided_by=order.approved_by,
                decided_at=approved_at,
            ),
        )

    def _record_order(
        self,
        cart: Cart,
        order: Order,
        result: PolicyResult,
        approved_by: User | None,
    ) -> None:
        self._record_approval(cart, approved_by, order.mandate_version, order.order_id)
        self._audit.record(
            AuditStep.POLICY,
            _GATEWAY_ACTOR,
            policy_sentence(result.decision, (reason.sentence for reason in result.reasons)),
            cart_id=cart.cart_id,
            input_data={"total_ex_vat": str(cart.total_ex_vat)},
            decision=result.decision,
            reason_codes=tuple(reason.reason_code for reason in result.reasons),
            mandate_version=order.mandate_version,
        )
        self._audit.record(
            AuditStep.ORDER,
            cart.agent_name if approved_by is None else approved_by.user_id,
            order_sentence(order.total_ex_vat),
            cart_id=cart.cart_id,
            output_data={"order_id": order.order_id},
            mandate_version=order.mandate_version,
        )

    def _record_approval(
        self,
        cart: Cart,
        approved_by: User | None,
        mandate_version: int,
        order_id: str | None = None,
    ) -> None:
        """No order_id: the gateway's next record says why no order followed."""
        if approved_by is None:
            return

        self._audit.record(
            AuditStep.APPROVAL,
            approved_by.user_id,
            f"Approved by {approved_by.user_id}.",
            cart_id=cart.cart_id,
            output_data=None if order_id is None else {"order_id": order_id},
            mandate_version=mandate_version,
        )


def _allows(decision: Decision, approved_by: User | None) -> bool:
    """AUTO always; HUMAN only with a person's approval; DENY never."""
    if decision is Decision.AUTO:
        return True

    return decision is Decision.HUMAN and approved_by is not None


def _order_line(line: CartLine, gtin: str | None) -> OrderLine:
    return OrderLine(
        product_id=line.product_id,
        gtin=gtin,
        name=line.name,
        qty=line.qty,
        unit_price=line.unit_price,
        line_total=line.line_total,
        delivery_date=line.delivery_date,
        substitute_for=line.substitute_for,
    )
