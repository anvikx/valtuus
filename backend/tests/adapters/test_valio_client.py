import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from app.adapters.valio_client import ValioClient
from app.adapters.valio_requests import ValioRequests
from app.domain.constants import GATEWAY_TIMEZONE
from app.domain.enums import StockModel, Unit
from app.domain.errors import UpstreamRateLimitedError, UpstreamUnavailableError
from app.domain.offer import ComparisonPrice

_MONDAY = date(2026, 11, 16)

# Shapes copied from live answers of 14 Nov 2026, trimmed to the fields the client reads.
_PRICE_ANSWER = {
    "currency": "EUR",
    "products": [
        {
            "productId": "464306",
            "catalogPrice": {
                "value": 1.01,
                "validFrom": "2026-09-01T00:00:00+0300",
                "validTo": "2026-12-31T00:00:00+0200",
            },
            "comparisonPrice": {"value": 1.01},
            "comparisonUnit": "L",
            "tax": {"taxRate": 13.5},
            "error": False,
        },
        {"productId": "000000", "error": True},
        {"productId": "111111", "catalogPrice": None, "error": False},
        {
            "productId": "222222",
            "catalogPrice": {
                "value": 0,
                "validFrom": "2026-09-01T00:00:00+0300",
                "validTo": "2026-12-31T00:00:00+0200",
            },
            "tax": {"taxRate": 13.5},
            "error": True,
        },
    ],
}
_AVAILABILITY_ANSWER = {
    "timeNow": "2026-11-14T15:38:58+0200",
    "products": [
        {
            "productId": "464306",
            "closingTime": "2026-11-15T17:00:00+0200",
            "salesBlock": False,
            "logisticModel": "Stock",
            "scheduleLines": [
                {
                    "salesBlock": False,
                    "availableAmount": 9999999999.0,
                    "availableDate": "2026-11-16",
                    "salesUnit": "ST",
                }
            ],
        },
        {
            "productId": "465039",
            "closingTime": "2026-11-12T15:00:00",
            "salesBlock": False,
            "logisticModel": "Terminal",
            "scheduleLines": [
                {"salesBlock": True, "availableAmount": 999999.0, "availableDate": "2026-11-16"}
            ],
        },
        {"productId": "000000", "salesBlock": False, "scheduleLines": []},
    ],
}


class _Upstream:
    """Stands in for urlopen: plays the given answers in order and records each call."""

    def __init__(self, *answers: object) -> None:
        self._answers = list(answers)
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request, timeout))
        answer = self._answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return BytesIO(json.dumps(answer).encode())


class _Time:
    def __init__(self) -> None:
        self.at = datetime(2026, 11, 14, tzinfo=GATEWAY_TIMEZONE)
        self.slept = []

    def now(self) -> datetime:
        return self.at

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.advance(seconds)


@pytest.fixture
def time(monkeypatch):
    fake = _Time()
    monkeypatch.setattr("app.adapters.valio_requests.sleep", fake.sleep)
    return fake


def _client(monkeypatch, upstream: _Upstream, clock: _Time) -> ValioClient:
    monkeypatch.setattr("app.adapters.valio_client.urlopen", upstream)
    return ValioClient(
        "https://example.test/api/", SecretStr("secret"), ValioRequests(clock), clock
    )


def _http_error(code: int) -> HTTPError:
    return HTTPError("https://example.test/api/price", code, "error", {}, None)


def test_prices_sends_the_ids_and_parses_numbers_as_exact_decimals(monkeypatch, time):
    upstream = _Upstream(_PRICE_ANSWER)

    prices = _client(monkeypatch, upstream, time).prices(["464306", "000000", "111111"], _MONDAY)

    request, timeout = upstream.calls[0]
    assert request.full_url == "https://example.test/api/price"
    assert request.get_header("X-api-key") == "secret"
    assert json.loads(request.data)["products"] == ["464306", "000000", "111111"]
    assert json.loads(request.data)["requestedDate"] == "2026-11-16"
    assert timeout > 0
    price = prices["464306"]
    # A float would give 1.0100000000000000088817841970012523233890533447265625.
    assert price.unit_price == Decimal("1.01")
    assert price.vat_rate == Decimal("13.5")
    assert price.comparison_price == ComparisonPrice(Decimal("1.01"), Unit.L)
    assert (price.valid_from, price.valid_to) == (date(2026, 9, 1), date(2026, 12, 31))


def test_a_product_with_no_price_is_absent(monkeypatch, time):
    """The offer rejects a missing product as NO_PRICE, so it must not appear with a zero price."""
    prices = _client(monkeypatch, _Upstream(_PRICE_ANSWER), time).prices(
        ["000000", "111111", "222222"], _MONDAY
    )

    assert prices == {}


def test_a_null_tax_is_an_unknown_vat_rate(monkeypatch, time):
    """One product with no tax must not fail the answer for every other product in the offer."""
    no_tax = {**_PRICE_ANSWER["products"][0], "productId": "333333", "tax": None}
    answer = {**_PRICE_ANSWER, "products": [*_PRICE_ANSWER["products"], no_tax]}

    prices = _client(monkeypatch, _Upstream(answer), time).prices(["464306", "333333"], _MONDAY)

    assert prices["333333"].vat_rate is None
    assert prices["464306"].vat_rate == Decimal("13.5")


def test_availability_keeps_the_raw_markers_and_reads_times_in_helsinki(monkeypatch, time):
    snapshot = _client(monkeypatch, _Upstream(_AVAILABILITY_ANSWER), time).availability(
        ["464306", "465039", "000000"], _MONDAY
    )

    assert snapshot.source_time == datetime(2026, 11, 14, 15, 38, 58, tzinfo=GATEWAY_TIMEZONE)
    stock = snapshot.items["464306"]
    assert stock.stock_model is StockModel.STOCK
    assert stock.amount == 9_999_999_999
    assert stock.available_date == _MONDAY
    assert stock.closing_time == datetime(2026, 11, 15, 17, tzinfo=GATEWAY_TIMEZONE)
    assert not stock.is_sales_blocked
    assert stock.sales_unit == "ST"
    terminal = snapshot.items["465039"]
    assert terminal.stock_model is StockModel.TERMINAL
    assert terminal.amount == 999_999
    # No zone in the text: Helsinki, not the server's zone and not UTC.
    assert terminal.closing_time == datetime(2026, 11, 12, 15, tzinfo=GATEWAY_TIMEZONE)
    assert terminal.closing_time.utcoffset() is not None
    assert terminal.is_sales_blocked
    unknown = snapshot.items["000000"]
    assert (unknown.stock_model, unknown.amount, unknown.available_date) == (None, None, None)
    assert unknown.closing_time is None
    assert unknown.sales_unit is None


def test_a_server_error_is_retried_with_a_growing_wait(monkeypatch, time):
    """A short outage must not fail the offer, and each wait gives the API more time to recover."""
    upstream = _Upstream(_http_error(503), _http_error(502), _PRICE_ANSWER)

    prices = _client(monkeypatch, upstream, time).prices(["464306"], _MONDAY)

    assert "464306" in prices
    assert len(upstream.calls) == 3
    assert time.slept == [0.5, 1.0]


@pytest.mark.parametrize(
    "failure",
    [_http_error(502), TimeoutError(), URLError(TimeoutError("timeout"))],
)
def test_a_third_failure_is_upstream_unavailable(monkeypatch, time, failure):
    """No offer from old or partial data: after 3 attempts the caller gets an error it can show."""
    upstream = _Upstream(failure, failure, failure)

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, upstream, time).prices(["464306"], _MONDAY)

    assert len(upstream.calls) == 3


def test_a_client_error_is_not_retried(monkeypatch, time):
    upstream = _Upstream(_http_error(422))

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, upstream, time).prices(["464306"], _MONDAY)

    assert len(upstream.calls) == 1


def test_a_connection_refusal_is_not_retried(monkeypatch, time):
    upstream = _Upstream(URLError(ConnectionRefusedError("refused")))

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, upstream, time).prices(["464306"], _MONDAY)

    assert len(upstream.calls) == 1
    assert time.slept == []


def test_a_429_on_the_retry_also_pauses_all_calls(monkeypatch, time):
    upstream = _Upstream(_http_error(503), _http_error(429))
    client = _client(monkeypatch, upstream, time)

    with pytest.raises(UpstreamRateLimitedError) as limited:
        client.prices(["464306"], _MONDAY)
    with pytest.raises(UpstreamRateLimitedError):
        client.availability(["464306"], _MONDAY)

    assert limited.value.retry_after == 30
    assert len(upstream.calls) == 2
    assert time.slept == [0.5]


def test_a_429_pauses_every_call_for_30_seconds(monkeypatch, time):
    """The mock blocks a caller for 30 s after a 429. A call in the pause only extends it."""
    upstream = _Upstream(_http_error(429), _AVAILABILITY_ANSWER)
    client = _client(monkeypatch, upstream, time)

    with pytest.raises(UpstreamRateLimitedError) as blocked:
        client.prices(["464306"], _MONDAY)
    time.advance(10)
    with pytest.raises(UpstreamRateLimitedError) as paused:
        client.availability(["464306"], _MONDAY)

    assert blocked.value.retry_after == 30
    assert len(upstream.calls) == 1
    assert paused.value.retry_after == 20
    assert paused.value.next_step == "Try again in 20 seconds."
    time.advance(20)
    client.availability(["464306"], _MONDAY)
    assert len(upstream.calls) == 2
    assert time.slept == []


def test_a_malformed_answer_is_upstream_unavailable(monkeypatch, time):
    upstream = _Upstream({"products": [{"productId": "464306", "catalogPrice": {}}]})

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, upstream, time).prices(["464306"], _MONDAY)


def _priced(product_id: object, value: object) -> dict:
    return {
        "products": [
            {
                "productId": product_id,
                "catalogPrice": {
                    "value": value,
                    "validFrom": "2026-09-01T00:00:00+0300",
                    "validTo": "2026-12-31T00:00:00+0200",
                },
                "tax": {"taxRate": 13.5},
                "error": False,
            }
        ]
    }


def _taxed(**fields: object) -> dict:
    """A priced answer with no tax key, plus the given fields."""
    answer = _priced("464306", 1.01)
    item = answer["products"][0]
    del item["tax"]
    item.update(fields)
    return answer


@pytest.mark.parametrize("value", [0, -1.5])
def test_a_price_of_zero_or_less_is_no_price(monkeypatch, time, value):
    """A zero price would rank first as the cheapest offer."""
    prices = _client(monkeypatch, _Upstream(_priced("464306", value)), time).prices(
        ["464306"],
        _MONDAY,
    )

    assert prices == {}


@pytest.mark.parametrize(
    "answer",
    [
        _priced("464306", float("nan")),
        _priced("464306", value=True),
        _priced("464306", "1.01"),
        _priced(464306, 1.01),
        {"products": _priced("464306", 1.01)["products"] * 2},
        _taxed(),
        _taxed(tax="13.5"),
        _taxed(tax={"taxRate": -1}),
    ],
    ids=[
        "nan",
        "bool",
        "string",
        "int id",
        "duplicate id",
        "no tax key",
        "tax text",
        "negative tax",
    ],
)
def test_a_broken_price_answer_is_upstream_unavailable(monkeypatch, time, answer):
    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, _Upstream(answer), time).prices(["464306"], _MONDAY)


@pytest.mark.parametrize(
    ("route", "answer"),
    [
        ("prices", {"products": [None]}),
        ("availability", {"timeNow": "2026-11-14T15:38:58", "products": [None]}),
        (
            "availability",
            {
                "timeNow": "2026-11-14T15:38:58",
                "products": [{"productId": "1", "scheduleLines": ["x"]}],
            },
        ),
    ],
    ids=["price entry", "stock entry", "schedule line"],
)
def test_an_entry_that_is_not_an_object_is_upstream_unavailable(monkeypatch, time, route, answer):
    """An AttributeError escaped the parser and answered 500 instead of failing closed."""
    client = _client(monkeypatch, _Upstream(answer), time)

    with pytest.raises(UpstreamUnavailableError):
        getattr(client, route)(["1"], _MONDAY)


@pytest.mark.parametrize("amount", [-3, True, "12"])
def test_a_broken_stock_amount_is_upstream_unavailable(monkeypatch, time, amount):
    line = {"availableAmount": amount, "availableDate": "2026-11-16"}
    answer = {
        "timeNow": "2026-11-14T15:38:58",
        "products": [{"productId": "1", "scheduleLines": [line]}],
    }

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, _Upstream(answer), time).availability(["1"], _MONDAY)


def test_a_repeated_call_within_60_seconds_uses_the_cached_answer(monkeypatch, time):
    """A repeated agent call must not hit the Valio API again, also for a product with no price."""
    upstream = _Upstream(_PRICE_ANSWER)
    client = _client(monkeypatch, upstream, time)
    first = client.prices(["464306", "000000"], _MONDAY)

    time.advance(59)
    again = client.prices(["464306", "000000"], _MONDAY)

    assert again == first
    assert set(again) == {"464306"}
    assert len(upstream.calls) == 1


def test_a_cached_answer_expires_after_60_seconds(monkeypatch, time):
    upstream = _Upstream(_PRICE_ANSWER, _PRICE_ANSWER)
    client = _client(monkeypatch, upstream, time)
    client.prices(["464306"], _MONDAY)

    time.advance(60)
    client.prices(["464306"], _MONDAY)

    assert len(upstream.calls) == 2


def test_the_cache_is_per_date(monkeypatch, time):
    """Price and stock depend on the delivery date, so one date must not answer for another."""
    upstream = _Upstream(_PRICE_ANSWER, _PRICE_ANSWER)
    client = _client(monkeypatch, upstream, time)
    client.prices(["464306"], _MONDAY)

    client.prices(["464306"], _MONDAY + timedelta(days=1))

    assert len(upstream.calls) == 2
    assert json.loads(upstream.calls[1][0].data)["requestedDate"] == "2026-11-17"


def test_only_the_products_not_in_the_cache_are_requested(monkeypatch, time):
    upstream = _Upstream(_PRICE_ANSWER, _PRICE_ANSWER)
    client = _client(monkeypatch, upstream, time)
    client.prices(["464306"], _MONDAY)

    prices = client.prices(["464306", "222222"], _MONDAY)

    assert json.loads(upstream.calls[1][0].data)["products"] == ["222222"]
    assert set(prices) == {"464306"}


def test_a_failure_is_not_cached(monkeypatch, time):
    """An outage must not block the next call for 60 seconds."""
    upstream = _Upstream(_http_error(422), _PRICE_ANSWER)
    client = _client(monkeypatch, upstream, time)
    with pytest.raises(UpstreamUnavailableError):
        client.prices(["464306"], _MONDAY)

    prices = client.prices(["464306"], _MONDAY)

    assert "464306" in prices
    assert len(upstream.calls) == 2


def test_a_mixed_stock_answer_shows_the_oldest_source_time(monkeypatch, time):
    """The offer must not claim stock is newer than the oldest answer it used."""
    later = {**_AVAILABILITY_ANSWER, "timeNow": "2026-11-14T15:39:28+0200"}
    upstream = _Upstream(_AVAILABILITY_ANSWER, later)
    client = _client(monkeypatch, upstream, time)
    client.availability(["464306"], _MONDAY)

    time.advance(30)
    snapshot = client.availability(["464306", "465039"], _MONDAY)

    assert json.loads(upstream.calls[1][0].data)["products"] == ["465039"]
    assert set(snapshot.items) == {"464306", "465039"}
    assert snapshot.source_time == datetime(2026, 11, 14, 15, 38, 58, tzinfo=GATEWAY_TIMEZONE)


def test_the_60_seconds_count_from_the_request_not_the_answer(monkeypatch, time):
    """Slow retries must not make an answer live longer than 60 seconds after it was asked."""
    upstream = _Upstream(_http_error(503), _http_error(503), _PRICE_ANSWER, _PRICE_ANSWER)
    client = _client(monkeypatch, upstream, time)
    client.prices(["464306"], _MONDAY)

    time.advance(60 - sum(time.slept))
    client.prices(["464306"], _MONDAY)

    assert len(upstream.calls) == 4
