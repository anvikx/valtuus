"""A search stores its full candidate set, so get_offers can price what the preview hides."""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import (
    InMemoryCartRepository,
    InMemoryOfferRepository,
    InMemorySearchSetRepository,
    InMemoryUnitOfWork,
)
from app.domain.constants import (
    MAX_OFFER_LINES,
    MAX_REJECTED_SHOWN,
    MAX_SEARCH_CANDIDATES,
    SEARCH_SET_TTL_MINUTES,
)
from app.domain.errors import InvalidRequestError, NotFoundError
from app.services.audit_service import AuditService
from app.services.offer_service import OfferService
from tests.adapters.samples import agent_key
from tests.fakes.catalog import item, query, service
from tests.fakes.offer_data import (
    NOW,
    FakeCatalog,
    FakePriceSource,
    MovableClock,
    price,
    stock,
)
from tests.fakes.offer_data import (
    query as offer_query,
)

_COUNT = MAX_SEARCH_CANDIDATES + 6
_IDS = [f"{n:03d}" for n in range(_COUNT)]
_CHEAPEST = _IDS[-1]


def _catalog() -> FakeCatalog:
    return FakeCatalog(*(item(pid) for pid in _IDS))


# The last id in the sort order is the cheapest, so the preview cannot show it.
_PRICES = [price(pid, "2.00") for pid in _IDS[:-1]] + [price(_CHEAPEST, "1.00")]


def _offers(catalog, search_sets, clock, prices=_PRICES, sink=None) -> OfferService:
    uow = InMemoryUnitOfWork()
    offers = InMemoryOfferRepository()
    return OfferService(
        catalog,
        FakePriceSource(prices, [stock(pid) for pid in _IDS]),
        offers,
        _NullSigner(),
        search_sets,
        clock,
        AuditService(sink or _Sink(), InMemoryCartRepository(), offers, clock, uow),
        uow,
        500,
    )


class _Sink:
    def __init__(self) -> None:
        self.records = []

    def append(self, record) -> None:
        self.records.append(record)


class _NullSigner:
    def sign(self, payload):
        return "s"


def _by_request(request_id, **fields):
    return replace(offer_query(), product_ids=(), request_id=request_id, **fields)


def _search(guard=500):
    search_sets = InMemorySearchSetRepository()
    catalog, records = service(_catalog(), candidate_guard=guard, search_sets=search_sets)
    return catalog, search_sets, records


def test_search_shows_a_preview_and_stores_every_hit():
    """The preview is capped for the agent. The offer must still see all hits."""
    catalog, search_sets, records = _search()

    result = catalog.search(agent_key(), query())

    assert len(result.candidates) == MAX_SEARCH_CANDIDATES
    stored = search_sets.get(result.request_id)
    assert stored.product_ids == tuple(_IDS)
    assert stored.buyer_id == agent_key().buyer_id
    assert result.hint.code == "READY"
    assert records.records[0].output_data["offer_set_size"] == _COUNT


def test_hits_over_the_guard_are_cut_and_flagged():
    """Only a cut of the stored set hides products from offers, so only it is GUARD_CUT."""
    catalog, search_sets, _ = _search(guard=_COUNT - 1)

    result = catalog.search(agent_key(), query())

    assert result.hint.code == "GUARD_CUT"
    assert len(search_sets.get(result.request_id).product_ids) == _COUNT - 1


def test_offers_by_request_id_price_a_product_outside_the_preview():
    """The cheapest product is past the 40 shown, and the price ranking must still find it."""
    catalog, search_sets, _ = _search()
    result = catalog.search(agent_key(), query())
    assert _CHEAPEST not in {c.product_id for c in result.candidates}
    offers = _offers(_catalog(), search_sets, FixedClock(NOW))

    offer = offers.get_offers(agent_key(), _by_request(result.request_id))

    assert offer.lines[0].product_id == _CHEAPEST
    assert offer.request_id == result.request_id


def test_offers_show_only_the_best_lines_and_count_the_rest():
    """A full category is too big for an MCP client. The rank compares every line first."""
    catalog, search_sets, _ = _search()
    result = catalog.search(agent_key(), query())
    offers = _offers(_catalog(), search_sets, FixedClock(NOW))

    offer = offers.get_offers(agent_key(), _by_request(result.request_id))

    assert len(offer.lines) == MAX_OFFER_LINES
    assert offer.lines_not_shown == _COUNT - MAX_OFFER_LINES
    assert offer.lines[0].product_id == _CHEAPEST


def test_offers_cut_the_rejected_list_but_audit_every_rejection():
    """The agent needs the reasons, not each product. The audit trail keeps each product."""
    catalog, search_sets, _ = _search()
    result = catalog.search(agent_key(), query())
    sink = _Sink()
    offers = _offers(_catalog(), search_sets, FixedClock(NOW), prices=[], sink=sink)

    offer = offers.get_offers(agent_key(), _by_request(result.request_id))

    assert len(offer.rejected) == MAX_REJECTED_SHOWN
    assert offer.rejected_not_shown == _COUNT - MAX_REJECTED_SHOWN
    assert len(sink.records[0].output_data["rejected"]) == _COUNT


def test_another_buyers_request_id_is_not_found():
    """Same answer as an unknown id, so nobody can probe other buyers' searches."""
    catalog, search_sets, _ = _search()
    result = catalog.search(agent_key(), query())
    offers = _offers(_catalog(), search_sets, FixedClock(NOW))

    with pytest.raises(NotFoundError):
        offers.get_offers(agent_key(buyer_id="other"), _by_request(result.request_id))


def test_an_unknown_request_id_is_not_found():
    offers = _offers(_catalog(), InMemorySearchSetRepository(), FixedClock(NOW))

    with pytest.raises(NotFoundError):
        offers.get_offers(agent_key(), _by_request("r_" + "0" * 32))


def test_an_expired_search_is_not_found():
    """An old set may list products that left the catalog, so it fails closed."""
    catalog, search_sets, _ = _search()
    result = catalog.search(agent_key(), query())
    clock = MovableClock(NOW)
    offers = _offers(_catalog(), search_sets, clock)
    clock.at = NOW + timedelta(minutes=SEARCH_SET_TTL_MINUTES + 1)

    with pytest.raises(NotFoundError):
        offers.get_offers(agent_key(), _by_request(result.request_id))


def test_no_product_ids_and_no_request_id_is_invalid():
    offers = _offers(_catalog(), InMemorySearchSetRepository(), FixedClock(NOW))

    with pytest.raises(InvalidRequestError):
        offers.get_offers(agent_key(), _by_request(None))
