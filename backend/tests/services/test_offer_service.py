from dataclasses import asdict
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import InMemoryOfferRepository, InMemoryUnitOfWork
from app.api.schemas.offers import OfferResponse
from app.domain.constants import GATEWAY_TIMEZONE
from app.domain.enums import AuditStep, ReasonCode
from app.domain.errors import (
    InvalidRequestError,
    UpstreamRateLimitedError,
    UpstreamUnavailableError,
)
from app.services.audit_service import AuditService
from app.services.offer_service import OfferService
from tests.adapters import samples
from tests.fakes.offer_data import (
    MILK_ID,
    MONDAY,
    NOW,
    SOURCE_TIME,
    FakeCatalog,
    FakePriceSource,
    price,
    product,
    query,
    stock,
)

_GUARD = 3
_SIGNATURE = "header.payload.signature"


class _Records:
    def __init__(self) -> None:
        self.records = []

    def append(self, record) -> None:
        self.records.append(record)


class _RecordingSigner:
    def __init__(self) -> None:
        self.payloads = []

    def sign(self, payload):
        self.payloads.append(payload)
        return _SIGNATURE


class _World:
    """The service with in-memory stores, so a test can look at what was kept."""

    def __init__(self, source: FakePriceSource, now: datetime = NOW) -> None:
        self.source = source
        self.offers = InMemoryOfferRepository()
        self.audit = _Records()
        self.signer = _RecordingSigner()
        clock = FixedClock(now)
        unit_of_work = InMemoryUnitOfWork()
        self.service = OfferService(
            FakeCatalog(product(), product("465039", sales_unit="KI")),
            source,
            self.offers,
            self.signer,
            clock,
            AuditService(self.audit, clock, unit_of_work),
            unit_of_work,
            _GUARD,
        )

    def get_offers(self, *product_ids: str, **fields):
        return self.service.get_offers(samples.agent_key(), query(*product_ids, **fields))


def _run_1() -> _World:
    return _World(FakePriceSource([price()], [stock()]))


def test_run_1_is_stored_as_returned_with_one_audit_record() -> None:
    """The cart reads its prices from the stored offer, never from the agent."""
    world = _run_1()

    offer = world.get_offers()

    assert world.offers.get(offer.offer_id) == offer
    assert offer.lines[0].product_id == MILK_ID
    assert offer.lines[0].line_total == Decimal("1010.00")
    assert offer.source_time == SOURCE_TIME
    assert offer.issued_at == NOW
    assert offer.buyer_id == samples.BUYER_ID
    (record,) = world.audit.records
    assert record.step is AuditStep.OFFER
    assert record.output_data["offer_id"] == offer.offer_id


def test_one_price_call_and_one_stock_call_for_all_ids() -> None:
    """The mock blocks a caller after a burst, so one call per product would hit a 429."""
    source = FakePriceSource([price(), price("465039")], [stock()])
    world = _World(source)

    world.get_offers(MILK_ID, "465039", MILK_ID)

    assert source.calls == [
        ("prices", (MILK_ID, "465039"), MONDAY),
        ("availability", (MILK_ID, "465039"), MONDAY),
    ]


def test_no_deliver_by_asks_for_the_next_day() -> None:
    world = _run_1()

    world.get_offers(deliver_by=None)

    assert {requested for *_, requested in world.source.calls} == {date(2026, 11, 15)}


def test_the_snapshot_holds_15_minutes() -> None:
    offer = _run_1().get_offers()

    assert offer.valid_until == NOW + timedelta(minutes=15)


def test_the_snapshot_ends_with_the_price() -> None:
    """At 23:50 a price that ends today must not hold until 00:05 tomorrow."""
    late_evening = datetime(2026, 11, 14, 23, 50, tzinfo=GATEWAY_TIMEZONE)
    source = FakePriceSource([price(valid_to=date(2026, 11, 14))], [stock()])

    offer = _World(source, late_evening).get_offers()

    assert offer.valid_until == datetime(2026, 11, 15, tzinfo=GATEWAY_TIMEZONE)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(UpstreamUnavailableError("down", "Try again in a minute."), id="down"),
        pytest.param(UpstreamRateLimitedError(30), id="rate limited"),
    ],
)
def test_an_upstream_failure_stores_nothing(error) -> None:
    """No offer from missing data, and no audit record of an offer that was never made."""
    world = _World(FakePriceSource(error=error))

    with pytest.raises(type(error)) as raised:
        world.get_offers()

    assert raised.value is error
    assert world.audit.records == []
    assert world.signer.payloads == []


def test_an_unknown_id_is_rejected_by_its_id_with_no_valio_call() -> None:
    world = _run_1()

    offer = world.get_offers("p_1")

    assert offer.lines == ()
    (rejected,) = offer.rejected
    assert (rejected.product_id, rejected.name) == ("p_1", "p_1")
    assert rejected.reason_code is ReasonCode.PRODUCT_NOT_FOUND
    assert rejected.reason_sentence
    assert world.source.calls == []


def test_an_offer_with_every_product_rejected_is_still_stored() -> None:
    """The agent and the audit must see why nothing can be ordered."""
    world = _World(FakePriceSource([price()], []))

    offer = world.get_offers(MILK_ID, "465039", "p_1")

    assert world.offers.get(offer.offer_id) == offer
    assert offer.lines == ()
    assert [item.reason_code for item in offer.rejected] == [
        ReasonCode.PRODUCT_NOT_FOUND,
        ReasonCode.NOT_AVAILABLE,
        ReasonCode.NO_PRICE,
    ]
    assert len(world.audit.records) == 1


def test_the_signature_covers_the_response_body_once() -> None:
    """The agent checks the signature on the body it got. Signing other bytes would fail it."""
    world = _run_1()

    offer = world.get_offers()

    (payload,) = world.signer.payloads
    body = asdict(offer)
    del body["signature"], body["buyer_id"]
    assert payload == body
    assert set(payload) == set(OfferResponse.model_fields) - {"signature"}
    assert offer.signature == _SIGNATURE
    assert world.offers.get(offer.offer_id).signature == _SIGNATURE


def test_more_ids_than_the_guard_is_refused_before_any_call() -> None:
    world = _run_1()

    with pytest.raises(InvalidRequestError):
        world.get_offers("a", "b", "c", "d")

    assert world.source.calls == []
