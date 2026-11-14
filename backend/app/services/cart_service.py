from collections.abc import Iterable, Sequence
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.domain.agent_key import AgentKey
from app.domain.cart import (
    OPEN_STATES,
    STATE_BY_DECISION,
    Cart,
    CartDraft,
    CartLine,
    CartLineInput,
    PricedLine,
)
from app.domain.constants import CURRENCY, GATEWAY_TIMEZONE, REJECT_MEMORY_MINUTES
from app.domain.enums import AuditStep, CartState, FlowPhase, ReasonCode
from app.domain.errors import ConflictError, InvalidRequestError, NotFoundError
from app.domain.idempotency import IdempotencyRecord, request_hash
from app.domain.mandate import Mandate
from app.domain.money import line_total, total_ex_vat
from app.domain.offer import Offer, OfferLine
from app.domain.order import Order
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.engine import PolicyEngine, PolicyResult, strictest
from app.domain.reason_text import day_text, reason_sentence
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

_OPERATION = "create_cart"
_GATEWAY_ACTOR = "gateway"
_WITHIN_MANDATE = "The cart is within the mandate."


class CartService:
    """Builds a cart from stored offer lines and runs the policy. Owns expiry on read."""

    def __init__(
        self,
        offers: OfferRepository,
        carts: CartRepository,
        orders: OrderRepository,
        idempotency: IdempotencyRepository,
        mandates: MandateService,
        policy: PolicyEngine,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._offers = offers
        self._carts = carts
        self._orders = orders
        self._idempotency = idempotency
        self._mandates = mandates
        self._policy = policy
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work

    def create_cart(self, agent: AgentKey, draft: CartDraft, idempotency_key: str) -> Cart:
        """A retry with the same key and body gets the first cart, read through get_cart."""
        fingerprint = request_hash(_OPERATION, asdict(draft))
        used = self._idempotency.get(agent.buyer_id, idempotency_key)
        if used is not None:
            return self._replay(used, fingerprint)

        # Every refusal comes before the first write: the memory store cannot roll back.
        cart, result = self._new_cart(agent, draft)
        with self._unit_of_work.transaction():
            self._claim(
                IdempotencyRecord(agent.buyer_id, idempotency_key, fingerprint, cart.cart_id)
            )
            self._carts.add(cart)
            self._record_cart(agent, draft, cart)
            self._record_policy(agent, cart, result)

        return cart

    def get_cart(self, buyer_id: str, cart_id: str) -> Cart:
        """Expiry on read first, then current_decision by the current mandate."""
        cart = self._carts.get(cart_id)
        if cart is None or cart.buyer_id != buyer_id:
            raise _cart_not_found(cart_id)

        return self._on_read(cart)

    def list_for_inbox(self, buyer_id: str) -> Sequence[Cart]:
        """Pending carts first, the earliest deadline on top. Then the rest, the latest first.

        ponytail: every cart of the buyer, each open one read as get_cart reads it, so each
        open cart runs the policy and reads the buyer's carts again. Add a page, and build the
        policy context once per list, when a buyer has more carts than one page shows.
        """
        carts = [self._on_read(cart) for cart in self._carts.for_buyer(buyer_id)]
        pending = [cart for cart in carts if cart.state is CartState.PENDING_APPROVAL]
        others = [cart for cart in carts if cart.state is not CartState.PENDING_APPROVAL]
        return [
            *sorted(pending, key=_by_deadline),
            *sorted(others, key=_by_deadline, reverse=True),
        ]

    def _on_read(self, cart: Cart) -> Cart:
        if cart.state not in OPEN_STATES:
            return cart

        now = self._clock.now()
        if now >= cart.approve_before:
            return self.locked_cart(cart.cart_id)

        return self._with_current_decision(cart, now)

    def locked_cart(self, cart_id: str) -> Cart:
        """The cart under its row lock, set to EXPIRED first if its deadline passed.

        Checkout and approve call it inside their own transaction, so the lock holds until
        their order is stored.
        """
        with self._unit_of_work.transaction():
            # Read again under the lock: a parallel read or an approve may have closed it.
            cart = self._carts.get_locked(cart_id)
            if cart is None:
                raise _cart_not_found(cart_id)
            if cart.state not in OPEN_STATES or self._clock.now() < cart.approve_before:
                return cart

            return self._expire(cart)

    def current_policy(self, cart: Cart, now: datetime) -> tuple[Mandate, PolicyResult]:
        """The policy on the cart's lines by the current mandate, as checkout and approve run it."""
        mandate = self._mandate(cart.buyer_id)
        lines = tuple(_priced_again(line) for line in cart.lines)
        context = self._context(cart.buyer_id, mandate, lines, now)
        # TODO: when the DUPLICATE_ORDER check lands, keep it from counting this cart as its
        # own duplicate after checkout places the order.
        return mandate, self._policy.decide(lines, context)

    def _replay(self, used: IdempotencyRecord, fingerprint: str) -> Cart:
        if used.request_hash != fingerprint:
            raise ConflictError(
                f"Idempotency-Key {used.key} was used for another cart request.",
                "Use a new Idempotency-Key for a new cart.",
            )

        return self.get_cart(used.buyer_id, used.result_id)

    def _claim(self, claim: IdempotencyRecord) -> None:
        """The first write, so a lost race stores nothing, also in the memory store."""
        try:
            self._idempotency.add(claim)
        except ValueError as error:
            raise ConflictError(
                f"Another call with Idempotency-Key {claim.key} made a cart first.",
                "Retry with the same Idempotency-Key to get that cart.",
            ) from error

    def _new_cart(self, agent: AgentKey, draft: CartDraft) -> tuple[Cart, PolicyResult]:
        now = self._clock.now()
        _refuse_repeated_products(draft.lines)
        offers = {item.offer_id: self._offer(agent.buyer_id, item.offer_id) for item in draft.lines}
        lines = tuple(_priced(item, offers[item.offer_id], now) for item in draft.lines)
        mandate = self._mandate(agent.buyer_id)
        context = self._context(agent.buyer_id, mandate, lines, now)
        result = self._policy.decide(lines, context)
        reason_codes = tuple(reason.reason_code for reason in result.reasons)
        cart = Cart(
            cart_id=f"c_{uuid4().hex}",
            buyer_id=agent.buyer_id,
            agent_name=agent.agent_name,
            state=STATE_BY_DECISION[result.decision],
            decision=result.decision,
            reason_codes=reason_codes,
            reason_sentences=tuple(reason.sentence for reason in result.reasons),
            current_decision=result.decision,
            current_reason_codes=reason_codes,
            request_text=draft.request_text,
            clarifications=draft.clarifications,
            interpreted_request=None,
            lines=tuple(_cart_line(line, result.reasons) for line in lines),
            total_ex_vat=total_ex_vat(line.line_total for line in lines),
            currency=CURRENCY,
            mandate_version=mandate.version,
            valid_until=min(offer.valid_until for offer in offers.values()),
            approve_before=min(line.closing_time for line in lines),
            duplicate_of_order_id=None,
            delivery_day_total_ex_vat=_delivery_day_total(lines, context.day_orders),
            order_id=None,
            previous_reject_reason=None,
            decided_by=None,
            decided_at=None,
            reject_reason=None,
        )
        return cart, result

    def _offer(self, buyer_id: str, offer_id: str) -> Offer:
        offer = self._offers.get(offer_id)
        # One answer for both cases, so an agent cannot probe other buyers' offer ids.
        if offer is None or offer.buyer_id != buyer_id:
            raise NotFoundError(
                f"Offer {offer_id} was not found.",
                "Get new offers, then make the cart from their lines.",
            )

        return offer

    def _mandate(self, buyer_id: str) -> Mandate:
        try:
            return self._mandates.get(buyer_id)
        except NotFoundError as error:
            # Every buyer is seeded with a mandate. A 404 would make the agent think its
            # offer or cart is gone, so this is a server fault with a log line.
            raise RuntimeError(f"buyer {buyer_id} has no mandate") from error

    def _context(
        self,
        buyer_id: str,
        mandate: Mandate,
        lines: Sequence[PricedLine],
        now: datetime,
    ) -> PolicyContext:
        day_orders = {
            order.order_id: order
            for day in _days(lines)
            for order in self._orders.for_day(buyer_id, day)
        }
        memory = timedelta(minutes=REJECT_MEMORY_MINUTES)
        recent_rejects = tuple(
            cart
            for cart in self._carts.for_buyer(buyer_id)
            if cart.state is CartState.REJECTED
            and cart.decided_at is not None
            and now - cart.decided_at < memory
        )
        return PolicyContext(
            mandate=mandate,
            day_orders=tuple(day_orders.values()),
            recent_rejects=recent_rejects,
            now=now,
        )

    def _with_current_decision(self, cart: Cart, now: datetime) -> Cart:
        """What checkout would decide now. Shown, not stored: the cart keeps its first decision."""
        _mandate, result = self.current_policy(cart, now)
        return replace(
            cart,
            current_decision=result.decision,
            current_reason_codes=tuple(reason.reason_code for reason in result.reasons),
        )

    def _expire(self, cart: Cart) -> Cart:
        sentence = reason_sentence(
            ReasonCode.CUTOFF_PASSED,
            deadline=_deadline_text(cart.approve_before),
        )
        expired = replace(
            cart,
            state=CartState.EXPIRED,
            reason_codes=(ReasonCode.CUTOFF_PASSED,),
            reason_sentences=(sentence,),
        )
        self._carts.save(expired)
        self._audit.record(
            AuditStep.CART,
            _GATEWAY_ACTOR,
            sentence,
            cart_id=cart.cart_id,
            phase=FlowPhase.ORDER,
            input_data={"state": cart.state},
            output_data={"state": expired.state},
            reason_codes=expired.reason_codes,
            mandate_version=cart.mandate_version,
        )
        return expired

    def _record_cart(self, agent: AgentKey, draft: CartDraft, cart: Cart) -> None:
        self._audit.record(
            AuditStep.CART,
            agent.agent_id,
            f"Cart {cart.cart_id}: {len(cart.lines)} lines, {cart.total_ex_vat} {CURRENCY}.",
            cart_id=cart.cart_id,
            phase=FlowPhase.ORDER,
            input_data={
                "lines": [asdict(item) for item in draft.lines],
                "request_text": draft.request_text,
                "clarifications": list(draft.clarifications),
            },
            output_data={
                "lines": [_priced_record(line) for line in cart.lines],
                "total_ex_vat": str(cart.total_ex_vat),
            },
        )

    def _record_policy(self, agent: AgentKey, cart: Cart, result: PolicyResult) -> None:
        self._audit.record(
            AuditStep.POLICY,
            agent.agent_id,
            " ".join(cart.reason_sentences) or _WITHIN_MANDATE,
            cart_id=cart.cart_id,
            phase=FlowPhase.ORDER,
            input_data={"total_ex_vat": str(cart.total_ex_vat)},
            output_data={"reason_sentences": list(cart.reason_sentences)},
            decision=result.decision,
            reason_codes=cart.reason_codes,
            mandate_version=cart.mandate_version,
        )


def _refuse_repeated_products(items: Sequence[CartLineInput]) -> None:
    # Reasons point at a line by product id, so two lines for one product would mix them up.
    product_ids = [item.product_id for item in items]
    if len(set(product_ids)) != len(product_ids):
        raise InvalidRequestError(
            "A product is in the cart more than one time.",
            "Send one line for each product, with the total qty.",
        )


def _priced(item: CartLineInput, offer: Offer, now: datetime) -> PricedLine:
    offer_line = _offer_line(offer, item.product_id)
    _refuse_closed(offer_line, now)
    _refuse_unpriced_date(offer_line)
    # valid_until is not checked: it limits only the stock snapshot, and checkout and
    # approve check stock again.
    return PricedLine(
        offer_id=item.offer_id,
        product_id=item.product_id,
        name=offer_line.name,
        qty=item.qty,
        unit_price=offer_line.unit_price,
        line_total=line_total(item.qty, offer_line.unit_price),
        delivery_date=offer_line.available_date,
        closing_time=offer_line.closing_time,
        substitute_for=offer_line.substitute_for,
    )


def _offer_line(offer: Offer, product_id: str) -> OfferLine:
    for offer_line in offer.lines:
        if offer_line.product_id == product_id:
            return offer_line

    raise InvalidRequestError(
        f"Product {product_id} is not a line of offer {offer.offer_id}.",
        "Use a product_id from the lines of that offer.",
    )


def _refuse_closed(offer_line: OfferLine, now: datetime) -> None:
    if now < offer_line.closing_time:
        return

    sentence = reason_sentence(
        ReasonCode.CUTOFF_PASSED,
        deadline=_deadline_text(offer_line.closing_time),
    )
    raise ConflictError(
        f"{ReasonCode.CUTOFF_PASSED}: product {offer_line.product_id}. {sentence}",
        "Get new offers, then make a new cart.",
    )


def _refuse_unpriced_date(offer_line: OfferLine) -> None:
    if offer_line.available_date <= offer_line.price_valid_to:
        return

    sentence = reason_sentence(
        ReasonCode.PRICE_NOT_VALID_FOR_DATE,
        price_valid_to=day_text(offer_line.price_valid_to),
        delivery_date=day_text(offer_line.available_date),
    )
    raise ConflictError(
        f"{ReasonCode.PRICE_NOT_VALID_FOR_DATE}: product {offer_line.product_id}. {sentence}",
        "Get new offers for a delivery date inside the price period.",
    )


def _cart_line(line: PricedLine, reasons: Iterable[CheckResult]) -> CartLine:
    own = [reason for reason in reasons if reason.line_id == line.product_id]
    return CartLine(
        offer_id=line.offer_id,
        product_id=line.product_id,
        name=line.name,
        qty=line.qty,
        unit_price=line.unit_price,
        line_total=line.line_total,
        delivery_date=line.delivery_date,
        closing_time=line.closing_time,
        decision=strictest(reason.decision for reason in own),
        substitute_for=line.substitute_for,
        reason_codes=tuple(reason.reason_code for reason in own),
        reason_sentences=tuple(reason.sentence for reason in own),
    )


def _priced_again(line: CartLine) -> PricedLine:
    return PricedLine(
        offer_id=line.offer_id,
        product_id=line.product_id,
        name=line.name,
        qty=line.qty,
        unit_price=line.unit_price,
        line_total=line.line_total,
        delivery_date=line.delivery_date,
        closing_time=line.closing_time,
        substitute_for=line.substitute_for,
    )


def _delivery_day_total(lines: Sequence[PricedLine], day_orders: Iterable[Order]) -> Decimal:
    """Every placed order on the date, approved ones too, plus this cart.

    ponytail: with lines on more than one date only the highest date total is shown.
    Enough for tier 1; give one total per date when the page shows a split delivery.
    """
    placed = [line for order in day_orders for line in order.lines]
    return max(
        total_ex_vat(
            [
                *(line.line_total for line in placed if line.delivery_date == day),
                *(line.line_total for line in lines if line.delivery_date == day),
            ]
        )
        for day in _days(lines)
    )


def _days(lines: Iterable[PricedLine]) -> set[date]:
    return {line.delivery_date for line in lines}


def _deadline_text(moment: datetime) -> str:
    """Sun 15 Nov 17:00 in gateway time. A Postgres read gives the time back in UTC."""
    local = moment.astimezone(GATEWAY_TIMEZONE)
    return f"{day_text(local.date())} {local:%H:%M}"


def _priced_record(line: CartLine) -> dict[str, object]:
    return {
        "offer_id": line.offer_id,
        "product_id": line.product_id,
        "qty": line.qty,
        "unit_price": str(line.unit_price),
        "line_total": str(line.line_total),
        "delivery_date": line.delivery_date.isoformat(),
    }


def _by_deadline(cart: Cart) -> tuple[datetime, str]:
    return cart.approve_before, cart.cart_id


def _cart_not_found(cart_id: str) -> NotFoundError:
    return NotFoundError(f"Cart {cart_id} was not found.", "Check the cart id, or make a new cart.")
