import re
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic_core import to_jsonable_python

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import (
    InMemoryCartRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemorySearchSetRepository,
    InMemoryUnitOfWork,
)
from app.adapters.postgres.offer_codec import OFFER_CODEC
from app.api.results import offer_response
from app.api.schemas.offers import OfferResponse
from app.domain.audit import REQUEST_ID_PATTERN
from app.domain.catalog import Allergens, ContentPerSalesUnit, Product
from app.domain.constants import GATEWAY_TIMEZONE
from app.domain.enums import AllergenStatus, AllergenType, AuditStep, ReasonCode, Unit
from app.domain.errors import (
    InvalidRequestError,
    NotFoundError,
    UpstreamRateLimitedError,
    UpstreamUnavailableError,
)
from app.services.audit_service import AuditService
from app.services.offer_service import OfferService
from tests.adapters import samples
from tests.fakes.offer_data import (
    CLOSING,
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
_REQUEST_ID = "r_0123456789abcdef0123456789abcdef"


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

    def __init__(
        self,
        source: FakePriceSource,
        now: datetime = NOW,
        *,
        products: tuple[Product, ...] | None = None,
    ) -> None:
        self.source = source
        self.offers = InMemoryOfferRepository()
        self.audit = _Records()
        self.signer = _RecordingSigner()
        self.clock = FixedClock(now)
        self.mandates = InMemoryMandateRepository()
        self.mandates.add(replace(samples.mandate(), preferred_brands=()))
        catalog_products = (
            (product(), product("465039", sales_unit="KI")) if products is None else products
        )
        unit_of_work = InMemoryUnitOfWork()
        self.service = OfferService(
            FakeCatalog(*catalog_products),
            source,
            self.offers,
            self.signer,
            InMemorySearchSetRepository(),
            self.clock,
            AuditService(
                self.audit,
                InMemoryCartRepository(),
                self.offers,
                self.clock,
                unit_of_work,
            ),
            unit_of_work,
            max(_GUARD, len(catalog_products)),
            self.mandates,
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


def test_offer_uses_current_mandate_brand():
    arla = replace(product("469363"), brand="Arla")
    world = _World(
        FakePriceSource(
            [price(), price("469363", "1.50")], [stock(), stock("469363", amount=2000)]
        ),
        products=(product(), arla),
    )
    world.mandates.add(
        replace(world.mandates.latest(samples.BUYER_ID), version=2, preferred_brands=("Arla",))
    )
    request = replace(query(MILK_ID, "469363"), preferred_brands=("Valio",))

    offer = world.service.get_offers(samples.agent_key(), request)

    assert offer.lines[0].brand == "Arla"
    assert world.audit.records[0].input_data["preferred_brands"] == ["Arla"]
    assert world.offers.get(offer.offer_id).lines == offer.lines
    payload = world.signer.payloads[0]
    expected = offer_response(offer).model_dump(mode="json")
    del expected["signature"]
    assert to_jsonable_python(payload) == expected
    assert OFFER_CODEC.validate_json(OFFER_CODEC.dump_json(offer)) == offer

    world.mandates.add(
        replace(world.mandates.latest(samples.BUYER_ID), version=3, preferred_brands=())
    )
    next_offer = world.service.get_offers(samples.agent_key(), query(MILK_ID, "469363"))

    assert next_offer.lines[0].brand == "Valio"


def test_offer_audit_records_mandate_version():
    """The mandate ranks the offer, so the audit must show which version did it."""
    world = _run_1()
    world.mandates.add(replace(world.mandates.latest(samples.BUYER_ID), version=2))

    world.service.get_offers(samples.agent_key(), query())

    assert world.audit.records[0].mandate_version == 2


def test_request_brand_applies_without_mandate_preference():
    world = _World(
        FakePriceSource([price(), price("arla", "1.50")], [stock(), stock("arla")]),
        products=(product(), replace(product("arla"), brand="Arla")),
    )

    offer = world.service.get_offers(
        samples.agent_key(), replace(query(MILK_ID, "arla"), preferred_brands=("Arla",))
    )

    assert offer.lines[0].brand == "Arla"


def test_offer_cannot_use_another_buyers_mandate():
    world = _run_1()

    with pytest.raises(NotFoundError, match="no mandate"):
        world.service.get_offers(samples.agent_key(buyer_id="other-buyer"), query())

    assert world.source.calls == []
    assert world.audit.records == []


def test_a_stored_offer_is_read_back_with_its_signature() -> None:
    """The approval page checks the signature, so the read must not drop it."""
    world = _run_1()
    offer = world.get_offers()

    read = world.service.get_offer(samples.BUYER_ID, offer.offer_id)

    assert read == offer
    assert read.signature == _SIGNATURE


@pytest.mark.parametrize("ask", [("other-buyer", None), (samples.BUYER_ID, "o_missing")])
def test_another_buyers_offer_reads_as_not_found(ask: tuple[str, str | None]) -> None:
    """One answer for a foreign and a missing id, so offer ids cannot be probed."""
    world = _run_1()
    offer = world.get_offers()
    buyer_id, offer_id = ask

    with pytest.raises(NotFoundError):
        world.service.get_offer(buyer_id, offer_id or offer.offer_id)


def test_the_request_id_of_the_search_goes_on_the_offer_and_its_record() -> None:
    """The audit joins the search and offer records to the cart by this id."""
    world = _run_1()

    offer = world.service.get_offers(samples.agent_key(), replace(query(), request_id=_REQUEST_ID))

    assert offer.request_id == _REQUEST_ID
    (record,) = world.audit.records
    assert record.request_id == _REQUEST_ID
    assert record.buyer_id == samples.BUYER_ID
    assert record.sentence == "The gateway offered 1 product."


def test_an_offer_with_no_search_starts_a_new_request() -> None:
    """An agent may skip search. Its offer still needs an id, or the audit cannot find it."""
    world = _run_1()

    first = world.get_offers()
    second = world.get_offers()

    assert re.fullmatch(REQUEST_ID_PATTERN, first.request_id)
    assert first.request_id != second.request_id
    assert [record.request_id for record in world.audit.records] == [
        first.request_id,
        second.request_id,
    ]


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


def test_a_price_with_no_end_holds_15_minutes() -> None:
    """Valio sends 9999-12-31 for a price with no end. The day after it must not break the offer.

    On 2026-11-14, 23 of 33 lactose free milk candidates had this date.
    """
    source = FakePriceSource([price(valid_to=date.max)], [stock()])

    offer = _World(source).get_offers()

    assert offer.valid_until == NOW + timedelta(minutes=15)


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
    (record,) = world.audit.records
    reasons = " ".join(item.reason_sentence for item in offer.rejected)
    assert record.sentence == f"The gateway offered 0 products and rejected 3: {reasons}"


def test_the_signature_covers_the_response_body_once() -> None:
    """The agent checks the signature on the body it got. Signing other bytes would fail it."""
    world = _run_1()

    offer = world.get_offers()

    (payload,) = world.signer.payloads
    response = offer_response(offer)
    body = asdict(offer)
    del body["signature"], body["buyer_id"]
    for line, public_line in zip(body["lines"], response.lines, strict=True):
        line["allergens"] = public_line.allergens.model_dump()

    assert payload == body
    assert response.lines[0].allergens.contains == ["AM"]
    assert response.lines[0].allergens.free_from == []
    assert set(payload) == set(OfferResponse.model_fields) - {"signature"}
    assert offer.signature == _SIGNATURE
    assert world.offers.get(offer.offer_id).signature == _SIGNATURE


@pytest.mark.parametrize("quantity", ["1000", "2.5"])
def test_the_signed_json_equals_the_response_json(quantity: str) -> None:
    """The agent compares the signed JSON with the body. A quantity is a number, not "2.5"."""
    world = _run_1()

    offer = world.get_offers(quantity=quantity)

    (payload,) = world.signer.payloads
    expected = offer_response(offer).model_dump(mode="json")
    del expected["signature"]
    assert to_jsonable_python(payload) == expected


def test_more_ids_than_the_guard_is_refused_before_any_call() -> None:
    world = _run_1()

    with pytest.raises(InvalidRequestError):
        world.get_offers("a", "b", "c", "d")

    assert world.source.calls == []


@pytest.mark.parametrize("unit", [Unit.L, Unit.KG, Unit.PCS])
def test_a_product_without_content_is_rejected_only_for_measured_requests(unit) -> None:
    world = _World(FakePriceSource([price()], [stock()]), products=(product(content=None),))

    offer = world.get_offers(quantity="4", unit=unit)

    assert world.offers.get(offer.offer_id) == offer
    if unit is Unit.PCS:
        assert offer.rejected == ()
        (line,) = offer.lines
        assert line.sales_units_needed == 4
        assert line.line_total == Decimal("4.04")
        assert line.reason_codes == ()
    else:
        assert offer.lines == ()
        (rejected,) = offer.rejected
        assert rejected.reason_code is ReasonCode.NO_CONTENT_DATA
        assert rejected.reason_sentence == "The size of this product is not in the data."


def test_every_candidate_is_ranked_or_rejected_with_a_reason_and_cutoff_details() -> None:
    ids = (MILK_ID, "expired", "unavailable", "unpriced", "no_content")
    products = tuple(
        product(pid, content=None) if pid == "no_content" else product(pid) for pid in ids
    )
    source = FakePriceSource(
        [price(pid) for pid in ids if pid != "unpriced"],
        [
            stock(),
            replace(stock("expired"), closing_time=NOW - timedelta(seconds=1)),
            stock("unavailable", amount=0),
            stock("unpriced"),
            stock("no_content"),
        ],
    )
    world = _World(source, products=products)

    offer = world.get_offers(*ids)

    assert [line.product_id for line in offer.lines] == [MILK_ID]
    assert {item.product_id: item.reason_code for item in offer.rejected} == {
        "expired": ReasonCode.CUTOFF_PASSED,
        "unavailable": ReasonCode.NOT_AVAILABLE,
        "unpriced": ReasonCode.NO_PRICE,
        "no_content": ReasonCode.NO_CONTENT_DATA,
    }
    assert len(offer.lines) + len(offer.rejected) == len(ids)
    assert all(item.reason_sentence for item in offer.rejected)
    (expired, *_) = offer.rejected
    assert expired.closing_time == NOW - timedelta(seconds=1)
    assert expired.reason_sentence == (
        "The order deadline Sat 14 Nov 15:38 has passed. Get new offers."
    )
    assert world.offers.get(offer.offer_id) == offer
    restored = OFFER_CODEC.validate_json(OFFER_CODEC.dump_json(offer))
    assert restored == offer
    response = offer_response(restored)
    assert response.rejected[0].closing_time == expired.closing_time
    assert response.rejected[0].reason_sentence == expired.reason_sentence
    (record,) = world.audit.records
    assert record.output_data["rejected"] == {
        item.product_id: item.reason_code for item in offer.rejected
    }
    assert expired.reason_sentence in record.sentence


def test_a_cutoff_crossed_during_the_upstream_call_is_rejected(monkeypatch) -> None:
    """Using the request's start time would offer a product whose deadline has now passed."""
    world = _run_1()
    availability = world.source.availability

    def slow_availability(product_ids, requested_date):
        answer = availability(product_ids, requested_date)
        monkeypatch.setattr(world.clock, "now", lambda: CLOSING)
        return answer

    monkeypatch.setattr(world.source, "availability", slow_availability)

    offer = world.get_offers()

    assert offer.lines == ()
    (rejected,) = offer.rejected
    assert rejected.reason_code is ReasonCode.CUTOFF_PASSED
    assert rejected.closing_time == CLOSING


_BOX_ID = "465039"


def _substitute_world(
    *,
    box_allergens: Allergens | None = None,
    milk_price: bool = True,
    milk_stock: bool = False,
) -> _World:
    """Run 5: 464306 cannot be delivered; Valio Aimo names the 5 l box 465039 in its place."""
    requested = replace(product(), substitute_ids=(_BOX_ID,))
    box = product(_BOX_ID, sales_unit="KI", content=ContentPerSalesUnit(Decimal(5), Unit.L))
    if box_allergens is not None:
        box = replace(box, allergens=box_allergens)
    prices = [price(), price(_BOX_ID, "5.25")] if milk_price else [price(_BOX_ID, "5.25")]
    stocks = [stock(_BOX_ID, sales_unit="KI"), *([stock()] if milk_stock else [])]
    source = FakePriceSource(prices, stocks)
    return _World(source, products=(requested, box))


def _with_substitutes(world: _World, *product_ids: str):
    asked = replace(query(*product_ids), include_substitutes=True)
    return world.service.get_offers(samples.agent_key(), asked)


def test_an_undeliverable_product_gets_its_equivalent_marked() -> None:
    """The mark lives in the signed, stored offer, so the agent cannot drop it from the cart."""
    world = _substitute_world()

    offer = _with_substitutes(world)

    (line,) = offer.lines
    assert line.product_id == _BOX_ID
    assert line.substitute_for.product_id == MILK_ID
    assert line.substitute_for.reason_code is ReasonCode.NOT_AVAILABLE
    assert line.substitute_for.price_difference_per_unit == Decimal("0.04")
    assert [item.reason_code for item in offer.rejected] == [ReasonCode.NOT_AVAILABLE]
    assert world.offers.get(offer.offer_id) == offer
    assert [(route, ids) for route, ids, _ in world.source.calls] == [
        ("prices", (MILK_ID,)),
        ("availability", (MILK_ID,)),
        ("prices", (_BOX_ID,)),
        ("availability", (_BOX_ID,)),
    ]


def test_no_substitute_unless_the_agent_asks() -> None:
    """For a generic ingredient every match is already a line; a swap would be noise."""
    world = _substitute_world()

    offer = world.get_offers()

    assert offer.lines == ()
    assert [ids for _, ids, _ in world.source.calls] == [(MILK_ID,), (MILK_ID,)]


def test_a_deliverable_product_gets_no_substitute() -> None:
    world = _substitute_world(milk_stock=True)

    offer = _with_substitutes(world)

    assert [line.product_id for line in offer.lines] == [MILK_ID]
    assert len(world.source.calls) == 2


def test_an_equivalent_with_other_allergens_is_not_offered() -> None:
    """Valio Aimo's pair is not proof of safety: the swap must not add an allergen."""
    soy = Allergens(AllergenStatus.KNOWN, (), {AllergenType.CONTAINS: ("AM", "AY")})
    world = _substitute_world(box_allergens=soy)

    offer = _with_substitutes(world)

    assert offer.lines == ()
    assert len(world.source.calls) == 2


def test_a_requested_equivalent_is_a_plain_line() -> None:
    """The agent asked for the box itself, so it replaces nothing."""
    world = _substitute_world()

    offer = _with_substitutes(world, MILK_ID, _BOX_ID)

    (line,) = offer.lines
    assert (line.product_id, line.substitute_for) == (_BOX_ID, None)


def test_a_requested_product_with_no_price_gives_no_difference() -> None:
    """The person still sees the substitute; the gateway does not invent a difference."""
    world = _substitute_world(milk_price=False)

    offer = _with_substitutes(world)

    (line,) = offer.lines
    assert line.substitute_for.reason_code is ReasonCode.NO_PRICE
    assert line.substitute_for.price_difference_per_unit is None
    assert offer_response(offer).lines[0].substitute_for.price_difference_per_unit is None
