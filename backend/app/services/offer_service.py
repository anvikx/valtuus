from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from app.domain.agent_key import AgentKey
from app.domain.audit import new_request_id
from app.domain.catalog import Product
from app.domain.constants import GATEWAY_TIMEZONE, OFFER_TTL_MINUTES
from app.domain.enums import AuditStep, FlowPhase, ReasonCode
from app.domain.errors import InvalidRequestError
from app.domain.offer import (
    AvailabilitySnapshot,
    Candidate,
    Offer,
    OfferLine,
    OfferQuery,
    Price,
    RejectedProduct,
    RequestedItem,
)
from app.domain.ranking import rank_offer_lines
from app.domain.screening import reject, screen
from app.services.audit_service import AuditService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.clock import Clock
from app.services.ports.price_source import PriceSource
from app.services.ports.repositories import OfferRepository
from app.services.ports.signer import Signer
from app.services.ports.unit_of_work import UnitOfWork

ISSUER = "Valio Aimo (mock)"


class OfferService:
    """One price call and one stock call per offer, then reject rules, ranking and split."""

    def __init__(
        self,
        catalog: ProductCatalog,
        prices: PriceSource,
        offers: OfferRepository,
        signer: Signer,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
        candidate_guard: int,
    ) -> None:
        self._catalog = catalog
        self._prices = prices
        self._offers = offers
        self._signer = signer
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work
        self._candidate_guard = candidate_guard

    def get_offers(self, agent: AgentKey, query: OfferQuery) -> Offer:
        """Raises UpstreamUnavailableError (and its rate limited kind) before anything is stored."""
        product_ids = tuple(dict.fromkeys(query.product_ids))
        if len(product_ids) > self._candidate_guard:
            raise InvalidRequestError(
                f"{len(product_ids)} product ids is over the limit of {self._candidate_guard}.",
                "Send fewer product ids.",
            )

        issued_at = self._clock.now()
        products, missing = self._products(product_ids)
        # No Valio call inside the transaction: a slow answer would hold the database lock.
        prices, snapshot = self._live_data(products, query, issued_at)
        candidates, rejected = _split(products, prices, snapshot, query)
        lines = rank_offer_lines(candidates, query)
        offer = self._signed(
            Offer(
                offer_id=f"o_{uuid4().hex}",
                buyer_id=agent.buyer_id,
                issuer=ISSUER,
                issued_at=issued_at,
                source_time=snapshot.source_time,
                valid_until=_valid_until(issued_at, lines),
                requested=RequestedItem(query.quantity, query.unit, query.deliver_by),
                lines=lines,
                proposed_split=None,
                rejected=missing + rejected,
                signature=None,
                request_id=query.request_id or new_request_id(),
            )
        )
        with self._unit_of_work.transaction():
            self._offers.add(offer)
            self._record(agent, query, offer)
        return offer

    def _products(
        self,
        product_ids: Sequence[str],
    ) -> tuple[tuple[Product, ...], tuple[RejectedProduct, ...]]:
        found = {pid: self._catalog.get(pid) for pid in product_ids}
        products = tuple(product for product in found.values() if product is not None)
        # The id stands in for the name: the agent sent it, so it can match the line.
        missing = tuple(
            reject(pid, pid, ReasonCode.PRODUCT_NOT_FOUND)
            for pid, product in found.items()
            if product is None
        )
        return products, missing

    def _live_data(
        self,
        products: Sequence[Product],
        query: OfferQuery,
        issued_at: datetime,
    ) -> tuple[Mapping[str, Price], AvailabilitySnapshot]:
        if not products:
            return {}, AvailabilitySnapshot(source_time=issued_at, items={})

        ids = [product.product_id for product in products]
        # No deliver_by asks for the earliest delivery: the next calendar day.
        requested_date = query.deliver_by or issued_at.date() + timedelta(days=1)
        return (
            self._prices.prices(ids, requested_date),
            self._prices.availability(ids, requested_date),
        )

    def _signed(self, offer: Offer) -> Offer:
        # The payload is the response body without its signature, built once. buyer_id is
        # stored, not sent, so a buyer agent can check the signature on what it got.
        body = asdict(offer)
        del body["signature"], body["buyer_id"]
        # asdict keeps internal declaration types, but the public body exposes their union.
        # Sign the same allergen fields the agent receives so that proof can match the body.
        for line, stored in zip(offer.lines, body["lines"], strict=True):
            stored["allergens"] = {
                "status": line.allergens.status,
                "contains": list(line.allergens.contains),
                "free_from": list(line.allergens.free_from),
            }
        return replace(offer, signature=self._signer.sign(body))

    def _record(self, agent: AgentKey, query: OfferQuery, offer: Offer) -> None:
        self._audit.record(
            AuditStep.OFFER,
            agent.agent_id,
            _offer_sentence(offer),
            request_id=offer.request_id,
            buyer_id=offer.buyer_id,
            phase=FlowPhase.LOOKUP,
            input_data={
                "product_ids": list(query.product_ids),
                "quantity": None if query.quantity is None else str(query.quantity),
                "unit": query.unit,
                "deliver_by": None if query.deliver_by is None else query.deliver_by.isoformat(),
            },
            output_data={
                "offer_id": offer.offer_id,
                "lines": [line.product_id for line in offer.lines],
                "rejected": {item.product_id: item.reason_code for item in offer.rejected},
            },
        )


def _offer_sentence(offer: Offer) -> str:
    """For example: The gateway offered 3 products and rejected 3: Order deadline passed."""
    count = len(offer.lines)
    offered = f"The gateway offered {count} product{'' if count == 1 else 's'}"
    if not offer.rejected:
        return f"{offered}."

    reasons = " ".join(dict.fromkeys(item.reason_sentence for item in offer.rejected))
    return f"{offered} and rejected {len(offer.rejected)}: {reasons}"


def _split(
    products: Sequence[Product],
    prices: Mapping[str, Price],
    snapshot: AvailabilitySnapshot,
    query: OfferQuery,
) -> tuple[list[Candidate], tuple[RejectedProduct, ...]]:
    candidates: list[Candidate] = []
    rejected: list[RejectedProduct] = []
    for product in products:
        pid = product.product_id
        result = screen(product, prices.get(pid), snapshot.items.get(pid), query)
        if isinstance(result, RejectedProduct):
            rejected.append(result)
            continue

        candidates.append(result)
    return candidates, tuple(rejected)


def _valid_until(issued_at: datetime, lines: Sequence[OfferLine]) -> datetime:
    """The stock snapshot holds 15 minutes, never past the end of the earliest price day."""
    ttl_end = issued_at + timedelta(minutes=OFFER_TTL_MINUTES)
    ends = [_day_after(line.price_valid_to) for line in lines]
    return min([ttl_end, *ends])


def _day_after(day: date) -> datetime:
    # An exclusive limit: the price holds all of valid_to, in Helsinki.
    return datetime.combine(day + timedelta(days=1), time(), tzinfo=GATEWAY_TIMEZONE)
