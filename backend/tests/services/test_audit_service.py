import pytest

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import (
    InMemoryAuditRepository,
    InMemoryCartRepository,
    InMemoryOfferRepository,
    InMemoryUnitOfWork,
)
from app.domain.errors import NotFoundError
from app.services.audit_service import AuditService
from tests.adapters import samples

# The request id of samples.offer.
_REQUEST_ID = "r_1"


class _World:
    """One stored cart whose line points at offer of_1 of request r_1."""

    def __init__(self) -> None:
        self.records = InMemoryAuditRepository()
        carts = InMemoryCartRepository()
        offers = InMemoryOfferRepository()
        carts.add(samples.cart())
        offers.add(samples.offer("of_1"))
        self.service = AuditService(
            self.records,
            carts,
            offers,
            FixedClock(samples.NOW),
            InMemoryUnitOfWork(),
        )

    def append(
        self,
        record_id: str,
        cart_id: str | None,
        request_id: str | None,
        buyer_id: str = samples.BUYER_ID,
    ) -> None:
        self.records.append(samples.audit_record(record_id, cart_id, request_id, buyer_id))


def test_the_trail_starts_at_the_search_before_the_cart() -> None:
    """The main user must see what the agent looked at, not only the cart it made."""
    world = _World()
    world.append("a_search", None, _REQUEST_ID)
    world.append("a_offer", None, _REQUEST_ID)
    world.append("a_cart", "c_1", None)

    records = world.service.for_cart(samples.BUYER_ID, "c_1")

    assert [record.record_id for record in records] == ["a_search", "a_offer", "a_cart"]


def test_the_trail_leaves_out_other_requests_and_carts() -> None:
    """A search the agent dropped, or another cart, is not part of this story."""
    world = _World()
    world.append("a_other_search", None, "r_2")
    world.append("a_other_cart", "c_2", None)
    world.append("a_cart", "c_1", None)

    records = world.service.for_cart(samples.BUYER_ID, "c_1")

    assert [record.record_id for record in records] == ["a_cart"]


def test_another_buyer_cannot_join_a_request() -> None:
    """An agent that sends another buyer's request id must not read or write that trail."""
    world = _World()
    world.append("a_search", None, _REQUEST_ID)
    world.append("a_intruder", None, _REQUEST_ID, buyer_id="hotel-2")

    records = world.service.for_cart(samples.BUYER_ID, "c_1")

    assert [record.record_id for record in records] == ["a_search"]


@pytest.mark.parametrize(
    ("buyer_id", "cart_id"),
    [
        pytest.param("hotel-2", "c_1", id="other buyer"),
        pytest.param(samples.BUYER_ID, "c_missing", id="missing cart"),
    ],
)
def test_a_cart_the_buyer_cannot_see_is_not_found(buyer_id: str, cart_id: str) -> None:
    """Another buyer must not learn that the cart exists, so both cases answer the same."""
    world = _World()
    world.append("a_cart", "c_1", None)

    with pytest.raises(NotFoundError):
        world.service.for_cart(buyer_id, cart_id)
