from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.domain.agent_key import AgentKey
from app.domain.audit import cart_sentence, policy_sentence, revision_sentence
from app.domain.cart import (
    OPEN_STATES,
    STATE_BY_DECISION,
    Cart,
    CartDraft,
    CartLine,
    CartLineInput,
    CartRevision,
    LineChange,
    PricedLine,
    cart_changes,
)
from app.domain.constants import CURRENCY, REJECT_MEMORY_MINUTES
from app.domain.enums import AuditStep, CartState, ReasonCode, RevisionAuthor
from app.domain.errors import ConflictError, InvalidRequestError, NotFoundError
from app.domain.idempotency import IdempotencyRecord, request_hash
from app.domain.mandate import Mandate
from app.domain.money import line_total, total_ex_vat
from app.domain.offer import Offer, OfferLine
from app.domain.order import Order
from app.domain.policy.baseline import build_baseline
from app.domain.policy.check import CheckResult, PolicyContext
from app.domain.policy.daily_limit import auto_day_total
from app.domain.policy.duplicate_order import duplicate_order
from app.domain.policy.engine import PolicyEngine, PolicyResult, strictest
from app.domain.policy.previously_rejected import rejected_cart
from app.domain.reason_text import day_text, deadline_text, reason_sentence
from app.services.audit_service import AuditService
from app.services.mandate_service import MandateService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.clock import Clock
from app.services.ports.repositories import (
    CartRepository,
    CartRevisionRepository,
    IdempotencyRepository,
    OfferRepository,
    OrderRepository,
)
from app.services.ports.unit_of_work import UnitOfWork

_OPERATION = "create_cart"
_REVISE = "revise_cart"
_GATEWAY_ACTOR = "gateway"
_WITHDRAW_SENTENCE = "The agent withdrew the cart."


@dataclass(frozen=True)
class _CartIdentity:
    """What a revision keeps from the cart. Everything else comes from the new lines."""

    cart_id: str
    buyer_id: str
    agent_name: str
    revision: int


@dataclass(frozen=True)
class CurrentPolicy:
    """A policy rerun, with the earlier order and reject its reasons point to."""

    mandate: Mandate
    result: PolicyResult
    duplicate_of_order_id: str | None
    previous_reject_reason: str | None


@dataclass(frozen=True)
class CartDetails:
    cart: Cart
    revision_count: int
    changes: tuple[LineChange, ...]


class CartService:
    """Builds a cart from stored offer lines and runs the policy. Owns expiry on read."""

    def __init__(
        self,
        offers: OfferRepository,
        carts: CartRepository,
        revisions: CartRevisionRepository,
        orders: OrderRepository,
        idempotency: IdempotencyRepository,
        mandates: MandateService,
        catalog: ProductCatalog,
        policy: PolicyEngine,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._offers = offers
        self._carts = carts
        self._revisions = revisions
        self._orders = orders
        self._idempotency = idempotency
        self._mandates = mandates
        self._catalog = catalog
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
            self._revisions.add(CartRevision(cart, RevisionAuthor.AGENT, self._clock.now()))
            sentence = cart_sentence((line.product_id for line in cart.lines), cart.total_ex_vat)
            self._record_cart(agent, draft, cart, sentence, {})
            self._record_policy(agent, cart, result)

        return cart

    def revise_cart(
        self,
        agent: AgentKey,
        cart_id: str,
        base_revision: int,
        draft: CartDraft,
        idempotency_key: str,
    ) -> Cart:
        """The next revision of an open cart, with the policy run from the start.

        A retry with the same key gets the cart as get_cart reads it now.
        """
        payload = {"cart_id": cart_id, "base_revision": base_revision, **asdict(draft)}
        fingerprint = request_hash(_REVISE, payload)
        used = self._idempotency.get(agent.buyer_id, idempotency_key)
        if used is not None:
            return self._replay(used, fingerprint)

        claim = IdempotencyRecord(agent.buyer_id, idempotency_key, fingerprint, cart_id)
        with self._unit_of_work.transaction():
            cart = self._locked_own(agent.buyer_id, cart_id)
            # A retry with the same key may have waited on the lock behind the first call. Its
            # base is now stale, so without this read it would get a 409, not its revision.
            used = self._idempotency.get(agent.buyer_id, idempotency_key)
            if used is not None:
                return self._replay(used, fingerprint)

            if cart.state in OPEN_STATES:
                return self._store_revision(agent, cart, base_revision, draft, claim)

        # After the commit, so an expiry found on the way is kept.
        raise _closed(cart)

    def withdraw_cart(self, agent: AgentKey, cart_id: str) -> Cart:
        """WITHDRAWN is final: the buyer no longer wants the cart, so nobody may approve it."""
        with self._unit_of_work.transaction():
            cart = self._locked_own(agent.buyer_id, cart_id)
            if cart.state in OPEN_STATES:
                return self._store_withdraw(agent, cart)

        raise _closed(cart)

    def get_cart(self, buyer_id: str, cart_id: str) -> Cart:
        """Expiry on read first, then current_decision by the current mandate."""
        cart = self._carts.get(cart_id)
        if cart is None or cart.buyer_id != buyer_id:
            raise _cart_not_found(cart_id)

        return self._on_read(cart)

    def get_cart_details(self, buyer_id: str, cart_id: str) -> CartDetails:
        """Read metadata only after ownership and expiry checks, without writing history."""
        cart = self.get_cart(buyer_id, cart_id)
        changes = cart.changes
        if changes is None:
            changes = self._legacy_changes(cart)
        return CartDetails(
            cart=cart,
            revision_count=cart.revision,
            changes=changes,
        )

    def _legacy_changes(self, cart: Cart) -> tuple[LineChange, ...]:
        """Old snapshots may lack the delta. Never compare against a version before N-1."""
        if cart.revision == 1:
            return ()

        previous = next(
            (
                item.cart
                for item in self._revisions.for_cart(cart.cart_id)
                if item.cart.revision == cart.revision - 1
            ),
            None,
        )
        return () if previous is None else cart_changes(previous.lines, cart.lines)

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

    def current_policy(self, cart: Cart, now: datetime) -> CurrentPolicy:
        """The policy on the cart's lines by the current mandate, as checkout and approve run it."""
        mandate = self._mandate(cart.buyer_id)
        lines = tuple(_priced_again(line) for line in cart.lines)
        context = self._context(cart.buyer_id, mandate, lines, now)
        # Only an open cart is rerun, and it has no order yet, so it is never its own duplicate.
        return CurrentPolicy(
            mandate=mandate,
            result=self._policy.decide(lines, context),
            duplicate_of_order_id=_duplicate_of(lines, context),
            previous_reject_reason=_previous_reject_reason(lines, context),
        )

    def _replay(self, used: IdempotencyRecord, fingerprint: str) -> Cart:
        if used.request_hash != fingerprint:
            raise ConflictError(
                f"Idempotency-Key {used.key} was used for another cart request.",
                "Use a new Idempotency-Key for each new cart or change.",
            )

        return self.get_cart(used.buyer_id, used.result_id)

    def _claim(self, claim: IdempotencyRecord) -> None:
        """The first write, so a lost race stores nothing, also in the memory store."""
        try:
            self._idempotency.add(claim)
        except ValueError as error:
            raise ConflictError(
                f"Another call with Idempotency-Key {claim.key} came first.",
                "Retry with the same Idempotency-Key to get that cart.",
            ) from error

    def _locked_own(self, buyer_id: str, cart_id: str) -> Cart:
        """The stored cart under its lock, EXPIRED first if its deadline passed."""
        cart = self._carts.get_locked(cart_id)
        if cart is None or cart.buyer_id != buyer_id:
            raise _cart_not_found(cart_id)

        return self.locked_cart(cart_id)

    def _store_revision(
        self,
        agent: AgentKey,
        cart: Cart,
        base_revision: int,
        draft: CartDraft,
        claim: IdempotencyRecord,
    ) -> Cart:
        # Every refusal comes before the first write: the memory store cannot roll back.
        if base_revision != cart.revision:
            raise _stale_base(cart)

        revised, result = self._decided(cart, draft)
        changes = cart_changes(cart.lines, revised.lines)
        revised = replace(revised, changes=changes)
        now = self._clock.now()
        self._claim(claim)
        self._keep_base(cart, now)
        self._carts.save(revised)
        self._revisions.add(CartRevision(revised, RevisionAuthor.AGENT, now))
        sentence = revision_sentence(
            revised.revision,
            RevisionAuthor.AGENT,
            changes,
            revised.total_ex_vat,
        )
        self._record_cart(agent, draft, revised, sentence, {"base_revision": base_revision})
        self._record_policy(agent, revised, result)
        return revised

    def _keep_base(self, cart: Cart, now: datetime) -> None:
        """A cart that an older gateway made after the revisions migration has no rows.

        Its base is stored now, so the next revision has one to compare with. The agent is
        the only author before a revision exists.
        """
        stored = {revision.cart.revision for revision in self._revisions.for_cart(cart.cart_id)}
        if cart.revision not in stored:
            self._revisions.add(CartRevision(cart, RevisionAuthor.AGENT, now))

    def _store_withdraw(self, agent: AgentKey, cart: Cart) -> Cart:
        withdrawn = replace(cart, state=CartState.WITHDRAWN)
        self._carts.save(withdrawn)
        self._audit.record(
            AuditStep.CART,
            agent.agent_id,
            _WITHDRAW_SENTENCE,
            cart_id=cart.cart_id,
            input_data={"state": cart.state, "revision": cart.revision},
            output_data={"state": withdrawn.state},
            mandate_version=cart.mandate_version,
        )
        return withdrawn

    def _new_cart(self, agent: AgentKey, draft: CartDraft) -> tuple[Cart, PolicyResult]:
        first = _CartIdentity(f"c_{uuid4().hex}", agent.buyer_id, agent.agent_name, revision=1)
        return self._built(first, draft)

    def _decided(self, cart: Cart, draft: CartDraft) -> tuple[Cart, PolicyResult]:
        """The next revision: same cart id and agent, new lines and a new decision."""
        following = _CartIdentity(
            cart.cart_id,
            cart.buyer_id,
            cart.agent_name,
            revision=cart.revision + 1,
        )
        return self._built(following, draft)

    def _built(self, identity: _CartIdentity, draft: CartDraft) -> tuple[Cart, PolicyResult]:
        now = self._clock.now()
        buyer_id = identity.buyer_id
        _refuse_repeated_products(draft.lines)
        offers = {item.offer_id: self._offer(buyer_id, item.offer_id) for item in draft.lines}
        lines = tuple(_priced(item, offers[item.offer_id], now) for item in draft.lines)
        mandate = self._mandate(buyer_id)
        context = self._context(buyer_id, mandate, lines, now)
        result = self._policy.decide(lines, context)
        reason_codes = tuple(reason.reason_code for reason in result.reasons)
        cart = Cart(
            cart_id=identity.cart_id,
            buyer_id=buyer_id,
            agent_name=identity.agent_name,
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
            duplicate_of_order_id=_duplicate_of(lines, context),
            delivery_day_total_ex_vat=_delivery_day_total(lines, context.day_orders),
            order_id=None,
            previous_reject_reason=_previous_reject_reason(lines, context),
            decided_by=None,
            decided_at=None,
            reject_reason=None,
            revision=identity.revision,
            changes=(),
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
            baseline=build_baseline(self._orders.list_confirmed(buyer_id)),
            offers={line.offer_id: self._offer(buyer_id, line.offer_id) for line in lines},
            day_orders=tuple(day_orders.values()),
            recent_rejects=recent_rejects,
            now=now,
            products={
                line.product_id: product
                for line in lines
                if (product := self._catalog.get(line.product_id)) is not None
            },
        )

    def _with_current_decision(self, cart: Cart, now: datetime) -> Cart:
        """What checkout would decide now. Shown, not stored: the cart keeps its first decision."""
        result = self.current_policy(cart, now).result
        return replace(
            cart,
            current_decision=result.decision,
            current_reason_codes=tuple(reason.reason_code for reason in result.reasons),
        )

    def _expire(self, cart: Cart) -> Cart:
        sentence = reason_sentence(
            ReasonCode.CUTOFF_PASSED,
            deadline=deadline_text(cart.approve_before),
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
            input_data={"state": cart.state},
            output_data={"state": expired.state},
            reason_codes=expired.reason_codes,
            mandate_version=cart.mandate_version,
        )
        return expired

    def _record_cart(
        self,
        agent: AgentKey,
        draft: CartDraft,
        cart: Cart,
        sentence: str,
        extra_input: Mapping[str, object],
    ) -> None:
        self._audit.record(
            AuditStep.CART,
            agent.agent_id,
            sentence,
            cart_id=cart.cart_id,
            input_data={
                **extra_input,
                "lines": [asdict(item) for item in draft.lines],
                "request_text": draft.request_text,
                "clarifications": list(draft.clarifications),
            },
            output_data={
                "revision": cart.revision,
                "lines": [_priced_record(line) for line in cart.lines],
                "total_ex_vat": str(cart.total_ex_vat),
            },
        )

    def _record_policy(self, agent: AgentKey, cart: Cart, result: PolicyResult) -> None:
        self._audit.record(
            AuditStep.POLICY,
            agent.agent_id,
            policy_sentence(result.decision, cart.reason_sentences),
            cart_id=cart.cart_id,
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
        stock_model=offer_line.stock_model,
        available_qty=offer_line.available_qty,
        needed_qty=offer_line.sales_units_needed,
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
        deadline=deadline_text(offer_line.closing_time),
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
        stock_model=line.stock_model,
        available_qty=line.available_qty,
        needed_qty=line.needed_qty,
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
        stock_model=line.stock_model,
        available_qty=line.available_qty,
        needed_qty=line.needed_qty,
    )


def _delivery_day_total(lines: Sequence[PricedLine], day_orders: Sequence[Order]) -> Decimal:
    """The same AUTO day total the daily limit checks, so the page and the decision agree.

    ponytail: with lines on more than one date only the highest date total is shown.
    Enough for tier 1; give one total per date when the page shows a split delivery.
    """
    return max(auto_day_total(day, lines, day_orders) for day in _days(lines))


def _duplicate_of(lines: Iterable[PricedLine], context: PolicyContext) -> str | None:
    """The order the DUPLICATE_ORDER reason names, so the page can link it."""
    for line in lines:
        order = duplicate_order(line, context.day_orders, context.now)
        if order is not None:
            return order.order_id

    return None


def _previous_reject_reason(lines: Iterable[PricedLine], context: PolicyContext) -> str | None:
    rejected = rejected_cart(lines, context.recent_rejects)
    return None if rejected is None else rejected.reject_reason


def _days(lines: Iterable[PricedLine]) -> set[date]:
    return {line.delivery_date for line in lines}


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


def _closed(cart: Cart) -> ConflictError:
    if cart.state is CartState.ORDERED:
        return ConflictError(
            f"Cart {cart.cart_id} is {cart.state}: already ordered. No change after an order.",
            "Tell the buyer it is already ordered, and make a new cart for the change.",
        )

    return ConflictError(
        f"Cart {cart.cart_id} is {cart.state}, so it cannot change.",
        "Read the cart to see why. Make a new cart for a new order.",
    )


def _stale_base(cart: Cart) -> ConflictError:
    current = cart.revision
    return ConflictError(
        f"Cart {cart.cart_id} is at revision {current}, not at the base_revision sent.",
        f"Read the cart, put the change on top of revision {current}, and send "
        f"base_revision {current}.",
    )
