import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest
from pydantic import SecretStr

from app.adapters.valio_client import ValioClient
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
        self.now = 1000.0
        self.slept = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def time(monkeypatch):
    fake = _Time()
    monkeypatch.setattr("app.adapters.valio_client.monotonic", fake.monotonic)
    monkeypatch.setattr("app.adapters.valio_client.sleep", fake.sleep)
    return fake


def _client(monkeypatch, upstream: _Upstream) -> ValioClient:
    monkeypatch.setattr("app.adapters.valio_client.urlopen", upstream)
    return ValioClient("https://example.test/api/", SecretStr("secret"))


def _http_error(code: int) -> HTTPError:
    return HTTPError("https://example.test/api/price", code, "error", {}, None)


def test_prices_sends_the_ids_and_parses_numbers_as_exact_decimals(monkeypatch, time):
    upstream = _Upstream(_PRICE_ANSWER)

    prices = _client(monkeypatch, upstream).prices(["464306", "000000", "111111"], _MONDAY)

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
    prices = _client(monkeypatch, _Upstream(_PRICE_ANSWER)).prices(
        ["000000", "111111", "222222"], _MONDAY
    )

    assert set(prices) == {"464306"}


def test_availability_keeps_the_raw_markers_and_reads_times_in_helsinki(monkeypatch, time):
    snapshot = _client(monkeypatch, _Upstream(_AVAILABILITY_ANSWER)).availability(
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


def test_a_server_error_is_retried_once(monkeypatch, time):
    upstream = _Upstream(_http_error(503), _PRICE_ANSWER)

    prices = _client(monkeypatch, upstream).prices(["464306"], _MONDAY)

    assert "464306" in prices
    assert len(upstream.calls) == 2


@pytest.mark.parametrize(
    "failure",
    [_http_error(502), TimeoutError(), URLError(ConnectionRefusedError("refused"))],
)
def test_a_second_failure_is_upstream_unavailable(monkeypatch, time, failure):
    """No offer from old or partial data: the caller gets an error it can show."""
    upstream = _Upstream(failure, failure)

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, upstream).prices(["464306"], _MONDAY)

    assert len(upstream.calls) == 2


def test_a_client_error_is_not_retried(monkeypatch, time):
    upstream = _Upstream(_http_error(422))

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, upstream).prices(["464306"], _MONDAY)

    assert len(upstream.calls) == 1


def test_a_429_pauses_every_call_for_30_seconds(monkeypatch, time):
    """The mock blocks a caller for 30 s after a 429. A call in the pause only extends it."""
    upstream = _Upstream(_http_error(429), _AVAILABILITY_ANSWER)
    client = _client(monkeypatch, upstream)

    with pytest.raises(UpstreamRateLimitedError) as blocked:
        client.prices(["464306"], _MONDAY)
    time.now += 10
    with pytest.raises(UpstreamRateLimitedError) as paused:
        client.availability(["464306"], _MONDAY)

    assert blocked.value.retry_after == 30
    assert len(upstream.calls) == 1
    assert paused.value.retry_after == 20
    assert paused.value.next_step == "Try again in 20 seconds."
    time.now += 20
    client.availability(["464306"], _MONDAY)
    assert len(upstream.calls) == 2
    assert time.slept == []


def test_a_malformed_answer_is_upstream_unavailable(monkeypatch, time):
    upstream = _Upstream({"products": [{"productId": "464306", "catalogPrice": {}}]})

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, upstream).prices(["464306"], _MONDAY)


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


@pytest.mark.parametrize("value", [0, -1.5])
def test_a_price_of_zero_or_less_is_no_price(monkeypatch, time, value):
    """A zero price would rank first as the cheapest offer."""
    prices = _client(monkeypatch, _Upstream(_priced("464306", value))).prices(["464306"], _MONDAY)

    assert prices == {}


@pytest.mark.parametrize(
    "answer",
    [
        _priced("464306", float("nan")),
        _priced("464306", value=True),
        _priced("464306", "1.01"),
        _priced(464306, 1.01),
        {"products": _priced("464306", 1.01)["products"] * 2},
    ],
    ids=["nan", "bool", "string", "int id", "duplicate id"],
)
def test_a_broken_price_answer_is_upstream_unavailable(monkeypatch, time, answer):
    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, _Upstream(answer)).prices(["464306"], _MONDAY)


@pytest.mark.parametrize("amount", [-3, True, "12"])
def test_a_broken_stock_amount_is_upstream_unavailable(monkeypatch, time, amount):
    line = {"availableAmount": amount, "availableDate": "2026-11-16"}
    answer = {
        "timeNow": "2026-11-14T15:38:58",
        "products": [{"productId": "1", "scheduleLines": [line]}],
    }

    with pytest.raises(UpstreamUnavailableError):
        _client(monkeypatch, _Upstream(answer)).availability(["1"], _MONDAY)
