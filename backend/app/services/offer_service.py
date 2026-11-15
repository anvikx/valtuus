from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from uuid import uuid4

from app.domain.agent_key import AgentKey
from app.domain.audit import new_request_id
from app.domain.catalog import Product
from app.domain.constants import (
    GATEWAY_TIMEZONE,
    MAX_OFFER_LINES,
    MAX_REJECTED_SHOWN,
    OFFER_TTL_MINUTES,
    SEARCH_SET_TTL_MINUTES,
)
from app.domain.enums import AuditStep, ReasonCode
from app.domain.errors import InvalidRequestError, NotFoundError
from app.domain.mandate import Mandate
from app.domain.offer import (
    AvailabilitySnapshot,
    Candidate,
    Offer,
    OfferLine,
    OfferQuery,
    Price,
    RejectedProduct,
    RequestedItem,
    SubstituteFor,
)
from app.domain.ranking import rank_offer_lines
from app.domain.screening import reject, screen
from app.domain.substitutes import is_equivalent, substitute_for
from app.domain.units import json_number
from app.services.audit_service import AuditService
from app.services.ports.catalog import ProductCatalog
from app.services.ports.clock import Clock
from app.services.ports.price_source import PriceSource
from app.services.ports.repositories import MandateRepository, OfferRepository, SearchSetRepository
from app.services.ports.signer import Signer
from app.services.ports.unit_of_work import UnitOfWork

ISSUER = "Valio Aimo (mock)"


@dataclass(frozen=True)
class _Equivalent:
    substitute: Product
    requested: Product
    rejected: RejectedProduct


class OfferService:
    """One price call and one stock call per offer, then reject rules, ranking and split.

    With include_substitutes, one more of each for the equivalents of rejected products.
    """

    def __init__(
        self,
        catalog: ProductCatalog,
        prices: PriceSource,
        offers: OfferRepository,
        signer: Signer,
        search_sets: SearchSetRepository,
        clock: Clock,
        audit: AuditService,
        unit_of_work: UnitOfWork,
        candidate_guard: int,
        mandates: MandateRepository,
    ) -> None:
        self._catalog = catalog
        self._prices = prices
        self._offers = offers
        self._signer = signer
        self._search_sets = search_sets
        self._clock = clock
        self._audit = audit
        self._unit_of_work = unit_of_work
        self._candidate_guard = candidate_guard
        self._mandates = mandates

    def get_offers(self, agent: AgentKey, query: OfferQuery) -> Offer:
        """Raises UpstreamUnavailableError (and its rate limited kind) before anything is stored."""
        product_ids = tuple(dict.fromkeys(query.product_ids or self._search_set_ids(agent, query)))
        if len(product_ids) > self._candidate_guard:
            raise InvalidRequestError(
                f"{len(product_ids)} product ids is over the limit of {self._candidate_guard}.",
                "Send fewer product ids.",
            )

        mandate = self._mandate(agent.buyer_id)
        query = replace(query, preferred_brands=mandate.preferred_brands or query.preferred_brands)
        issued_at = self._clock.now()
        products, missing = self._products(product_ids)
        # No Valio call inside the transaction: a slow answer would hold the database lock.
        prices, snapshot = self._live_data(products, query, issued_at)
        # A deadline may pass while the upstream answers; screen against the time after it.
        candidates, screened_out = _split(products, prices, snapshot, query, self._clock.now())
        # The first snapshot is the older one, so it stays the offer's source_time.
        substitutes = self._substitutes(products, prices, screened_out, query, issued_at)
        ranked = rank_offer_lines(candidates, query, substitutes)
        rejected = missing + screened_out
        # Cut after the rank, so the lines shown are the best of all priced products.
        lines = ranked[:MAX_OFFER_LINES]
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
                rejected=rejected[:MAX_REJECTED_SHOWN],
                signature=None,
                request_id=query.request_id or new_request_id(),
                lines_not_shown=len(ranked) - len(lines),
                rejected_not_shown=max(len(rejected) - MAX_REJECTED_SHOWN, 0),
            )
        )
        with self._unit_of_work.transaction():
            self._offers.add(offer)
            self._record(agent, query, offer, rejected, mandate.version)
        return offer

    def _search_set_ids(self, agent: AgentKey, query: OfferQuery) -> tuple[str, ...]:
        if query.request_id is None:
            raise InvalidRequestError(
                "Send product_ids or the request_id of a search.",
                "Send product_ids, or the request_id of a search with no product_ids.",
            )

        found = self._search_sets.get(query.request_id)
        expired = found is not None and self._clock.now() - found.created_at > timedelta(
            minutes=SEARCH_SET_TTL_MINUTES
        )
        # One answer for all cases, so nobody can probe other buyers' search ids.
        if found is None or found.buyer_id != agent.buyer_id or expired:
            raise NotFoundError(
                f"Search {query.request_id} was not found or has expired.",
                "Search again, then send its request_id with no product_ids.",
            )

        return found.product_ids

    def get_offer(self, buyer_id: str, offer_id: str) -> Offer:
        """The stored offer with its signature, so the approval page can check what it shows."""
        offer = self._offers.get(offer_id)
        # One answer for both cases, so nobody can probe other buyers' offer ids.
        if offer is None or offer.buyer_id != buyer_id:
            raise NotFoundError(f"Offer {offer_id} was not found.", "Check the offer id.")

        return offer

    def _mandate(self, buyer_id: str) -> Mandate:
        with self._unit_of_work.transaction():
            mandate = self._mandates.latest(buyer_id)
        if mandate is None:
            raise NotFoundError("The buyer has no mandate.", "Ask the buyer to set a mandate.")
        return mandate

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

    def _substitutes(
        self,
        requested: Sequence[Product],
        prices: Mapping[str, Price],
        screened_out: Sequence[RejectedProduct],
        query: OfferQuery,
        issued_at: datetime,
    ) -> list[tuple[Candidate, SubstituteFor]]:
        if not query.include_substitutes:
            return []

        wanted = self._equivalents(requested, screened_out)
        if not wanted:
            return []

        products = [item.substitute for item in wanted.values()]
        live_prices, snapshot = self._live_data(products, query, issued_at)
        # A substitute that fails the reject rules is dropped: the agent asked for the original.
        candidates, _ = _split(products, live_prices, snapshot, query, self._clock.now())
        return [
            (candidate, _marked(wanted[candidate.product.product_id], prices, candidate, query))
            for candidate in candidates
        ]

    def _equivalents(
        self,
        requested: Sequence[Product],
        screened_out: Sequence[RejectedProduct],
    ) -> dict[str, _Equivalent]:
        by_id = {product.product_id: product for product in requested}
        wanted: dict[str, _Equivalent] = {}
        for rejected in screened_out:
            original = by_id[rejected.product_id]
            # A requested id is already its own line, and the first rejected product wins a
            # substitute that two of them share.
            fresh = (
                sid for sid in original.substitute_ids if sid not in by_id and sid not in wanted
            )
            for substitute in filter(None, map(self._catalog.get, fresh)):
                if is_equivalent(original, substitute):
                    wanted[substitute.product_id] = _Equivalent(substitute, original, rejected)
        # ponytail: a product names at most 5 substitutes, so the guard caps the upstream ids
        # and cuts the last equivalents. Batch the Valio calls if more must be priced.
        return dict(list(wanted.items())[: self._candidate_guard])

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
        # The body sends the quantity as a JSON number. As a Decimal it would sign "2.5".
        quantity = offer.requested.quantity
        body["requested"]["quantity"] = None if quantity is None else json_number(quantity)
        return replace(offer, signature=self._signer.sign(body))

    def _record(
        self,
        agent: AgentKey,
        query: OfferQuery,
        offer: Offer,
        rejected: Sequence[RejectedProduct],
        mandate_version: int,
    ) -> None:
        # rejected is the full list: the offer shows only the first ones.
        self._audit.record(
            AuditStep.OFFER,
            agent.agent_id,
            _offer_sentence(offer, rejected),
            request_id=offer.request_id,
            buyer_id=offer.buyer_id,
            input_data={
                "product_ids": list(query.product_ids),
                "quantity": None if query.quantity is None else str(query.quantity),
                "unit": query.unit,
                "deliver_by": None if query.deliver_by is None else query.deliver_by.isoformat(),
                "preferred_brands": list(query.preferred_brands),
            },
            output_data={
                "offer_id": offer.offer_id,
                "lines": [line.product_id for line in offer.lines],
                "lines_not_shown": offer.lines_not_shown,
                "rejected": {item.product_id: item.reason_code for item in rejected},
            },
            mandate_version=mandate_version,
        )


def _offer_sentence(offer: Offer, rejected: Sequence[RejectedProduct]) -> str:
    """For example: The gateway offered 3 products and rejected 3: Order deadline passed."""
    count = len(offer.lines)
    offered = f"The gateway offered {count} product{'' if count == 1 else 's'}"
    if not rejected:
        return f"{offered}."

    reasons = " ".join(dict.fromkeys(item.reason_sentence for item in rejected))
    return f"{offered} and rejected {len(rejected)}: {reasons}"


def _split(
    products: Sequence[Product],
    prices: Mapping[str, Price],
    snapshot: AvailabilitySnapshot,
    query: OfferQuery,
    now: datetime,
) -> tuple[list[Candidate], tuple[RejectedProduct, ...]]:
    candidates: list[Candidate] = []
    rejected: list[RejectedProduct] = []
    for product in products:
        pid = product.product_id
        result = screen(product, prices.get(pid), snapshot.items.get(pid), query, now)
        if isinstance(result, RejectedProduct):
            rejected.append(result)
            continue

        candidates.append(result)
    return candidates, tuple(rejected)


def _marked(
    equivalent: _Equivalent,
    prices: Mapping[str, Price],
    candidate: Candidate,
    query: OfferQuery,
) -> SubstituteFor:
    requested = equivalent.requested
    return substitute_for(
        requested,
        prices.get(requested.product_id),
        equivalent.rejected,
        candidate,
        query,
    )


def _valid_until(issued_at: datetime, lines: Sequence[OfferLine]) -> datetime:
    """The stock snapshot holds 15 minutes, never past the end of the earliest price day."""
    ttl_end = issued_at + timedelta(minutes=OFFER_TTL_MINUTES)
    # Valio sends 9999-12-31 for a price with no end. The day after it is past date.max and
    # raised OverflowError, so a price with no end does not limit the offer.
    ends = [_day_after(line.price_valid_to) for line in lines if line.price_valid_to < date.max]
    return min([ttl_end, *ends])


def _day_after(day: date) -> datetime:
    # An exclusive limit: the price holds all of valid_to, in Helsinki.
    return datetime.combine(day + timedelta(days=1), time(), tzinfo=GATEWAY_TIMEZONE)
