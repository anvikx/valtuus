from collections.abc import Mapping, Sequence
from uuid import uuid4

from app.domain.audit import AuditRecord, audit_phase
from app.domain.cart import Cart
from app.domain.enums import AuditStep, Decision, ReasonCode
from app.domain.errors import NotFoundError
from app.services.ports.clock import Clock
from app.services.ports.repositories import AuditRepository, CartRepository, OfferRepository
from app.services.ports.unit_of_work import UnitOfWork


class AuditService:
    """The only writer of audit records. Any service may call it."""

    def __init__(
        self,
        records: AuditRepository,
        carts: CartRepository,
        offers: OfferRepository,
        clock: Clock,
        unit_of_work: UnitOfWork,
    ) -> None:
        self._records = records
        # Leaf services do not call each other, so the cart and its offers come from their
        # repositories.
        self._carts = carts
        self._offers = offers
        self._clock = clock
        self._unit_of_work = unit_of_work

    def record(
        self,
        step: AuditStep,
        actor: str,
        sentence: str,
        cart_id: str | None = None,
        request_id: str | None = None,
        buyer_id: str | None = None,
        input_data: Mapping[str, object] | None = None,
        output_data: Mapping[str, object] | None = None,
        decision: Decision | None = None,
        reason_codes: Sequence[ReasonCode] = (),
        mandate_version: int | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            record_id=f"a_{uuid4().hex}",
            cart_id=cart_id,
            request_id=request_id,
            step=step,
            phase=audit_phase(step, cart_id),
            actor=actor,
            input_data=input_data or {},
            output_data=output_data or {},
            decision=decision,
            reason_codes=tuple(reason_codes),
            mandate_version=mandate_version,
            sentence=sentence,
            created_at=self._clock.now(),
            buyer_id=buyer_id,
        )
        self._records.append(record)
        return record

    def record_refusal(
        self,
        actor: str,
        sentence: str,
        reason: ReasonCode,
        input_data: Mapping[str, object],
    ) -> AuditRecord:
        """A refused call changes no state, so its record needs a transaction of its own."""
        with self._unit_of_work.transaction():
            return self.record(
                AuditStep.REFUSED,
                actor,
                sentence,
                input_data=input_data,
                reason_codes=(reason,),
            )

    def for_cart(self, buyer_id: str, cart_id: str) -> Sequence[AuditRecord]:
        """The cart's records and the search and offer records before it, oldest first.

        A plain read: it writes no record and does not expire the cart.
        """
        cart = self._carts.get(cart_id)
        if cart is None or cart.buyer_id != buyer_id:
            raise NotFoundError(
                f"Cart {cart_id} was not found.",
                "Check the cart id, or make a new cart.",
            )

        return self._records.for_cart(
            cart_id,
            buyer_id=buyer_id,
            request_ids=self._request_ids(cart),
        )

    def _request_ids(self, cart: Cart) -> tuple[str, ...]:
        offer_ids = dict.fromkeys(line.offer_id for line in cart.lines)
        offers = (self._offers.get(offer_id) for offer_id in offer_ids)
        request_ids = (offer.request_id for offer in offers if offer is not None)
        return tuple(dict.fromkeys(rid for rid in request_ids if rid is not None))
