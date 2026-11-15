"""Fake HTTP answers through the real Valio client and offer rules. No network or database."""

import json
from datetime import datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from io import BytesIO
from urllib.error import HTTPError

import pytest
from pydantic import SecretStr

from app.adapters.clock import FixedClock
from app.adapters.memory.repositories import (
    InMemoryCartRepository,
    InMemoryMandateRepository,
    InMemoryOfferRepository,
    InMemoryUnitOfWork,
)
from app.adapters.signer import NullSigner
from app.adapters.valio_client import ValioClient
from app.adapters.valio_requests import ValioRequests
from app.domain.enums import ReasonCode, StockModel
from app.domain.errors import UpstreamUnavailableError
from app.services.audit_service import AuditService
from app.services.offer_service import OfferService
from tests.adapters import samples
from tests.fakes.offer_data import (
    CLOSING,
    MILK_ID,
    NOW,
    SOURCE_TIME,
    FakeCatalog,
    product,
    query,
)

_CONTROL_ID = "another-product"
_IDS = (MILK_ID, _CONTROL_ID)


def _price_item(product_id):
    return {
        "productId": product_id,
        "catalogPrice": {
            "value": 1.01,
            "validFrom": "2026-09-01T00:00:00+0300",
            "validTo": "2026-12-31T00:00:00+0200",
        },
        "tax": {"taxRate": 13.5},
        "error": False,
    }


def _stock_item(product_id):
    return {
        "productId": product_id,
        "closingTime": CLOSING.isoformat(),
        "salesBlock": False,
        "logisticModel": "Stock",
        "scheduleLines": [
            {
                "salesBlock": False,
                "availableAmount": 100,
                "availableDate": "2026-11-16",
                "salesUnit": "ST",
            }
        ],
    }


class _Upstream:
    def __init__(self):
        self.answers = {
            "price": {"products": [_price_item(pid) for pid in _IDS]},
            "availability": {
                "timeNow": SOURCE_TIME.isoformat(),
                "products": [_stock_item(pid) for pid in _IDS],
            },
        }
        self.calls = []

    def __call__(self, request, timeout):
        route = request.full_url.rsplit("/", 1)[-1]
        self.calls.append(route)
        answer = self.answers[route]
        if isinstance(answer, BaseException):
            raise answer
        return BytesIO(json.dumps(answer).encode())


class _OfferStore(InMemoryOfferRepository):
    def __init__(self):
        super().__init__()
        self.added = []

    def add(self, offer):
        self.added.append(offer)
        super().add(offer)


class _AuditLog:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


class _World:
    def __init__(self, monkeypatch):
        self.upstream = _Upstream()
        self.clock = FixedClock(NOW)
        self.offers = _OfferStore()
        self.audit = _AuditLog()
        self.waits = []
        monkeypatch.setattr("app.adapters.valio_client.urlopen", self.upstream)
        monkeypatch.setattr("app.adapters.valio_requests.sleep", self.waits.append)
        client = ValioClient(
            "https://example.test/api",
            SecretStr("test-valio-key"),
            ValioRequests(self.clock),
            self.clock,
        )
        unit_of_work = InMemoryUnitOfWork()
        mandates = InMemoryMandateRepository()
        mandates.add(samples.mandate())
        audit = AuditService(
            self.audit,
            InMemoryCartRepository(),
            self.offers,
            self.clock,
            unit_of_work,
        )
        self.service = OfferService(
            FakeCatalog(*(product(pid) for pid in _IDS)),
            client,
            self.offers,
            NullSigner(),
            self.clock,
            audit,
            unit_of_work,
            len(_IDS),
            mandates,
        )

    def get_offers(self):
        return self.service.get_offers(samples.agent_key(), query(*_IDS, quantity="20"))

    def price_item(self):
        return self.upstream.answers["price"]["products"][0]

    def stock_item(self):
        return self.upstream.answers["availability"]["products"][0]


@pytest.fixture
def world(monkeypatch):
    return _World(monkeypatch)


@pytest.mark.parametrize(
    ("price_changes", "stock_changes", "schedule_changes", "code"),
    [
        pytest.param(
            {},
            {"closingTime": None},
            {},
            ReasonCode.DEADLINE_UNKNOWN,
            id="null-closing-time-DEADLINE_UNKNOWN",
        ),
        pytest.param(
            {},
            {"salesBlock": True},
            {},
            ReasonCode.SALES_BLOCKED,
            id="product-sales-block-SALES_BLOCKED",
        ),
        pytest.param(
            {},
            {},
            {"salesBlock": True},
            ReasonCode.SALES_BLOCKED,
            id="schedule-sales-block-SALES_BLOCKED",
        ),
        pytest.param({"catalogPrice": None}, {}, {}, ReasonCode.NO_PRICE, id="null-price-NO_PRICE"),
        pytest.param({"error": True}, {}, {}, ReasonCode.NO_PRICE, id="price-error-NO_PRICE"),
        pytest.param(
            {},
            {"closingTime": (NOW - timedelta(seconds=1)).isoformat()},
            {},
            ReasonCode.CUTOFF_PASSED,
            id="passed-closing-time-CUTOFF_PASSED",
        ),
        pytest.param(
            {},
            {"closingTime": NOW.isoformat()},
            {},
            ReasonCode.CUTOFF_PASSED,
            id="at-closing-time-CUTOFF_PASSED",
        ),
        pytest.param(
            {}, {"scheduleLines": []}, {}, ReasonCode.NOT_AVAILABLE, id="no-schedule-NOT_AVAILABLE"
        ),
        pytest.param(
            {}, {}, {"availableAmount": 0}, ReasonCode.NOT_AVAILABLE, id="zero-amount-NOT_AVAILABLE"
        ),
        pytest.param(
            {},
            {},
            {"availableDate": None},
            ReasonCode.NOT_AVAILABLE,
            id="null-delivery-date-NOT_AVAILABLE",
        ),
    ],
)
def test_bad_api_data_excludes_only_the_affected_product(
    world,
    price_changes,
    stock_changes,
    schedule_changes,
    code,
):
    """One bad product must be explained, while another product's valid offer remains usable."""
    world.price_item().update(price_changes)
    world.stock_item().update(stock_changes)
    if schedule_changes:
        world.stock_item()["scheduleLines"][0].update(schedule_changes)

    offer = world.get_offers()

    assert [line.product_id for line in offer.lines] == [_CONTROL_ID]
    (rejected,) = offer.rejected
    assert rejected.product_id == MILK_ID
    assert rejected.reason_code is code
    assert rejected.reason_sentence
    if code is ReasonCode.CUTOFF_PASSED:
        assert rejected.closing_time == datetime.fromisoformat(world.stock_item()["closingTime"])
        assert "Get new offers" in rejected.reason_sentence
    assert world.offers.get(offer.offer_id) == offer
    (record,) = world.audit.records
    assert record.output_data["rejected"] == {MILK_ID: code}
    assert world.upstream.calls == ["price", "availability"]


@pytest.mark.parametrize(
    ("model", "amount"),
    [
        pytest.param(None, 100, id="null-logistic-model"),
        pytest.param("Terminal", 999999, id="terminal-unknown-amount"),
        pytest.param("Stock", 999999, id="stock-unknown-amount-marker"),
    ],
)
def test_unknown_stock_is_disclosed_without_a_confirmed_quantity(world, model, amount):
    """Unknown stock may be proposed for human review, never promised as a confirmed count."""
    world.stock_item()["logisticModel"] = model
    world.stock_item()["scheduleLines"][0]["availableAmount"] = amount

    offer = world.get_offers()

    assert offer.rejected == ()
    line = next(line for line in offer.lines if line.product_id == MILK_ID)
    assert line.available_qty is None
    assert line.stock_model is (
        StockModel.STOCK
        if model == "Stock"
        else StockModel.TERMINAL
        if model == "Terminal"
        else None
    )
    assert line.reason_codes == (ReasonCode.STOCK_UNCONFIRMED,)
    assert line.reason_sentences == ("Valio Aimo does not confirm the stock of this product.",)


@pytest.mark.parametrize("route", ["price", "availability"])
@pytest.mark.parametrize("failure", ["server-error", "timeout"])
def test_failed_api_raises_instead_of_creating_an_offer(world, route, failure):
    error = (
        HTTPError("https://example.test/api", HTTPStatus.SERVICE_UNAVAILABLE, "down", {}, None)
        if failure == "server-error"
        else TimeoutError("timed out")
    )
    world.upstream.answers[route] = error

    with pytest.raises(UpstreamUnavailableError) as raised:
        world.get_offers()

    assert raised.value.next_step
    assert world.upstream.calls.count(route) == 3
    assert world.waits == [0.5, 1.0]
    assert world.offers.added == []
    assert world.audit.records == []


@pytest.mark.parametrize("route", ["price", "availability"])
def test_malformed_api_answer_raises_instead_of_creating_an_offer(world, route):
    world.upstream.answers[route]["products"] = [None]

    with pytest.raises(UpstreamUnavailableError):
        world.get_offers()

    assert world.upstream.calls.count(route) == 1
    assert world.offers.added == []
    assert world.audit.records == []


@pytest.mark.parametrize("route", ["price", "availability"])
def test_expired_cache_does_not_hide_an_api_failure(world, monkeypatch, route):
    first = world.get_offers()
    monkeypatch.setattr(world.clock, "now", lambda: NOW + timedelta(seconds=60))
    world.upstream.answers[route] = HTTPError(
        "https://example.test/api",
        HTTPStatus.SERVICE_UNAVAILABLE,
        "down",
        {},
        None,
    )

    with pytest.raises(UpstreamUnavailableError):
        world.get_offers()

    assert world.offers.added == [first]
    assert len(world.audit.records) == 1


@pytest.mark.parametrize(
    ("amount", "expected_quantity"),
    [
        pytest.param(100, 100, id="counted-stock"),
        pytest.param(9999999999, None, id="in-stock-marker-is-not-a-quantity"),
    ],
)
def test_valid_api_answer_preserves_the_confirmed_stock_and_exact_price(
    world, amount, expected_quantity
):
    for item in world.upstream.answers["availability"]["products"]:
        item["scheduleLines"][0]["availableAmount"] = amount

    offer = world.get_offers()

    assert offer.rejected == ()
    assert {line.product_id for line in offer.lines} == set(_IDS)
    for line in offer.lines:
        assert line.stock_model is StockModel.STOCK
        assert line.available_qty == expected_quantity
        assert line.unit_price == Decimal("1.01")
        assert line.line_total == Decimal("20.20")
        assert line.reason_codes == ()
    assert offer.source_time == SOURCE_TIME
