"""The Valio Aimo price and availability APIs, parsed into domain values."""

import json
import logging
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from http.client import HTTPException
from time import monotonic, sleep
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pydantic import SecretStr

from app.domain.constants import GATEWAY_TIMEZONE, VALIO_COOLDOWN_SECONDS
from app.domain.enums import StockModel, Unit
from app.domain.errors import UpstreamUnavailableError
from app.domain.offer import Availability, AvailabilitySnapshot, ComparisonPrice, Price

_LOG = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 10
_RETRY_WAIT_SECONDS = 0.5
_TOO_MANY_REQUESTS = 429
_SERVER_ERROR = 500
# The API ignores the customer field and gives every buyer the same price.
_CUSTOMER = "valtuus"
_STOCK_MODELS = {"Stock": StockModel.STOCK, "Terminal": StockModel.TERMINAL}
_PARSE_ERRORS = (KeyError, IndexError, TypeError, ValueError, ArithmeticError)

type _Json = dict[str, Any]


class ValioClient:
    """The Valio Aimo price and availability APIs. Raises UpstreamUnavailableError."""

    def __init__(self, base_url: str, api_key: SecretStr) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        # Shared by both routes: the mock blocks the caller, not one route.
        self._paused_until = 0.0

    def prices(self, product_ids: Sequence[str], requested_date: date) -> Mapping[str, Price]:
        answer = self._post("price", product_ids, requested_date)
        return _parsed(_prices, answer)

    def availability(
        self,
        product_ids: Sequence[str],
        requested_date: date,
    ) -> AvailabilitySnapshot:
        answer = self._post("availability", product_ids, requested_date)
        return _parsed(_snapshot, answer)

    def _post(self, route: str, product_ids: Sequence[str], requested_date: date) -> _Json:
        # A call during the pause would extend the mock's block, so it fails here at once.
        wait = math.ceil(self._paused_until - monotonic())
        if wait > 0:
            raise _unavailable(f"Try again in {wait} seconds.")

        body = {
            "customer": _CUSTOMER,
            "requestedDate": requested_date.isoformat(),
            "products": list(product_ids),
        }
        request = Request(
            f"{self._base_url}/{route}",
            data=json.dumps(body).encode(),
            headers={
                "X-API-Key": self._api_key.get_secret_value(),
                "Content-Type": "application/json",
                # The upstream's Cloudflare policy rejects urllib's default user agent.
                "User-Agent": "curl/8.7.1",
            },
        )
        try:
            return _send_with_retry(request)
        except HTTPError as exc:
            if exc.code != _TOO_MANY_REQUESTS:
                raise _unavailable() from exc

            self._paused_until = monotonic() + VALIO_COOLDOWN_SECONDS
            _LOG.warning("Valio %s answered 429. Pausing all calls.", route)
            raise _unavailable(f"Try again in {VALIO_COOLDOWN_SECONDS} seconds.") from exc
        except (OSError, HTTPException, ValueError) as exc:
            raise _unavailable() from exc


def _send_with_retry(request: Request) -> _Json:
    """One more try after a server error or a timeout. A 429 or another 4xx is not retried."""
    try:
        return _send(request)
    except HTTPError as exc:
        if exc.code < _SERVER_ERROR:
            raise
    except OSError:
        pass

    sleep(_RETRY_WAIT_SECONDS)
    return _send(request)


def _send(request: Request) -> _Json:
    with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
        # Floats would turn 1.01 into 1.0100000000000000088... before it reaches a money sum.
        return json.loads(response.read(), parse_float=Decimal, parse_int=Decimal)


def _parsed[T](parse: Callable[[_Json], T], answer: _Json) -> T:
    # A missing or wrong field must not become a zero price or an empty stock.
    try:
        return parse(answer)
    except _PARSE_ERRORS as exc:
        raise _unavailable() from exc


def _unavailable(next_step: str = "Try again in a minute.") -> UpstreamUnavailableError:
    return UpstreamUnavailableError(
        "The Valio Aimo price or stock service did not answer.",
        next_step,
    )


def _prices(answer: _Json) -> dict[str, Price]:
    prices = (_price(item) for item in answer["products"])
    return _by_id(price for price in prices if price is not None)


def _price(item: _Json) -> Price | None:
    """None for a product with no price: the offer then rejects it with NO_PRICE."""
    catalog = item.get("catalogPrice")
    if item.get("error") or catalog is None:
        return None

    # A zero price would rank first as the cheapest offer.
    unit_price = _number(catalog["value"])
    if unit_price <= 0:
        return None

    return Price(
        product_id=_text(item["productId"]),
        unit_price=unit_price,
        vat_rate=_not_negative(item["tax"]["taxRate"]),
        comparison_price=_comparison(item),
        valid_from=_helsinki(catalog["validFrom"]).date(),
        valid_to=_helsinki(catalog["validTo"]).date(),
    )


def _comparison(item: _Json) -> ComparisonPrice | None:
    comparison = item.get("comparisonPrice")
    unit = item.get("comparisonUnit")
    if comparison is None or unit not in Unit:
        return None

    return ComparisonPrice(value=_number(comparison["value"]), per=Unit(unit))


def _snapshot(answer: _Json) -> AvailabilitySnapshot:
    items = (_availability(item) for item in answer["products"])
    return AvailabilitySnapshot(
        source_time=_helsinki(answer["timeNow"]),
        items=_by_id(items),
    )


def _availability(item: _Json) -> Availability:
    # The first schedule line is the earliest date. No line means the mock cannot deliver.
    first = (item.get("scheduleLines") or [{}])[0]
    amount = first.get("availableAmount")
    available_date = first.get("availableDate")
    closing_time = item.get("closingTime")
    return Availability(
        product_id=_text(item["productId"]),
        stock_model=_STOCK_MODELS.get(item.get("logisticModel")),
        # The markers 999999 and 9999999999 stay raw numbers. A part of a sales unit cannot be
        # ordered, so 2.5 is 2.
        amount=None if amount is None else int(_not_negative(amount)),
        available_date=None if available_date is None else date.fromisoformat(available_date),
        closing_time=None if closing_time is None else _helsinki(closing_time),
        is_sales_blocked=bool(item.get("salesBlock") or first.get("salesBlock")),
    )


def _by_id[T: (Price, Availability)](values: Iterable[T]) -> dict[str, T]:
    by_id: dict[str, T] = {}
    for value in values:
        # Two lines for one product: keeping either one would hide the other.
        if value.product_id in by_id:
            raise ValueError(f"duplicate product {value.product_id}")

        by_id[value.product_id] = value
    return by_id


def _number(value: object) -> Decimal:
    # parse_float and parse_int give Decimal. A bool, a string or a NaN float is a broken answer.
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"not a number: {value!r}")

    return value


def _not_negative(value: object) -> Decimal:
    number = _number(value)
    if number < 0:
        raise ValueError(f"negative: {number}")

    return number


def _text(value: object) -> str:
    # An int id would miss every lookup by the catalog's string id.
    if not isinstance(value, str):
        raise TypeError(f"not a string: {value!r}")

    return value


def _helsinki(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    # Every time seen so far has a zone. A time without one is the mock's local time.
    if moment.tzinfo is None:
        return moment.replace(tzinfo=GATEWAY_TIMEZONE)

    return moment.astimezone(GATEWAY_TIMEZONE)
