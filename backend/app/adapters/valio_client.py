"""The Valio Aimo price and availability APIs, parsed into domain values."""

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from http.client import HTTPException
from threading import Lock
from typing import Any
from urllib.request import Request, urlopen

from pydantic import SecretStr

from app.adapters.valio_requests import ValioRequests
from app.domain.constants import GATEWAY_TIMEZONE, VALIO_CACHE_SECONDS
from app.domain.enums import StockModel, Unit
from app.domain.errors import UpstreamUnavailableError
from app.domain.offer import Availability, AvailabilitySnapshot, ComparisonPrice, Price
from app.services.ports.clock import Clock

_TIMEOUT_SECONDS = 10
# The API ignores the customer field and gives every buyer the same price.
_CUSTOMER = "valtuus"
_STOCK_MODELS = {"Stock": StockModel.STOCK, "Terminal": StockModel.TERMINAL}
_PARSE_ERRORS = (KeyError, IndexError, TypeError, ValueError, ArithmeticError, AttributeError)

type _Json = dict[str, Any]


@dataclass(frozen=True)
class _Stock:
    source_time: datetime
    item: Availability | None


class _AnswerCache[T]:
    """One answer per (product, date). None in a value is a cached "no price" or "no stock"."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._entries: dict[tuple[str, date], tuple[datetime, T]] = {}
        # Routes run in a thread pool, so two calls can fill the cache at once.
        self._lock = Lock()

    def get_or_fetch(
        self,
        product_ids: Sequence[str],
        day: date,
        fetch: Callable[[list[str], date], Mapping[str, T]],
    ) -> dict[str, T]:
        found = self._fresh(product_ids, day)
        missing = [pid for pid in dict.fromkeys(product_ids) if pid not in found]
        if not missing:
            return found

        # Read before the fetch: slow retries must not extend the life of the answer.
        asked_at = self._clock.now()
        # The fetch runs without the lock: a slow upstream must not block cache hits.
        fetched = fetch(missing, day)
        self._store(fetched, day, asked_at)
        return found | dict(fetched)

    def _fresh(self, product_ids: Sequence[str], day: date) -> dict[str, T]:
        oldest = self._clock.now() - timedelta(seconds=VALIO_CACHE_SECONDS)
        with self._lock:
            entries = ((pid, self._entries.get((pid, day))) for pid in product_ids)
            return {pid: entry[1] for pid, entry in entries if entry and entry[0] > oldest}

    def _store(self, values: Mapping[str, T], day: date, asked_at: datetime) -> None:
        oldest = self._clock.now() - timedelta(seconds=VALIO_CACHE_SECONDS)
        with self._lock:
            # Drop expired entries so the cache holds at most one minute of answers.
            self._entries = {
                key: entry for key, entry in self._entries.items() if entry[0] > oldest
            }
            self._entries.update(((pid, day), (asked_at, value)) for pid, value in values.items())


class ValioClient:
    """The Valio Aimo price and availability APIs. Raises UpstreamUnavailableError."""

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        requests: ValioRequests,
        clock: Clock,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._requests = requests
        self._clock = clock
        self._price_cache = _AnswerCache[Price | None](clock)
        self._stock_cache = _AnswerCache[_Stock](clock)

    def prices(self, product_ids: Sequence[str], requested_date: date) -> Mapping[str, Price]:
        prices = self._price_cache.get_or_fetch(product_ids, requested_date, self._fetch_prices)
        return {pid: price for pid, price in prices.items() if price is not None}

    def availability(
        self,
        product_ids: Sequence[str],
        requested_date: date,
    ) -> AvailabilitySnapshot:
        stock = self._stock_cache.get_or_fetch(product_ids, requested_date, self._fetch_stock)
        return AvailabilitySnapshot(
            # Answers of different calls: the oldest one is how old this stock can be.
            source_time=min(
                (entry.source_time for entry in stock.values()), default=self._clock.now()
            ),
            items={pid: entry.item for pid, entry in stock.items() if entry.item is not None},
        )

    def _fetch_prices(self, product_ids: list[str], day: date) -> dict[str, Price | None]:
        prices = _parsed(_prices, self._post("price", product_ids, day))
        return {pid: prices.get(pid) for pid in product_ids}

    def _fetch_stock(self, product_ids: list[str], day: date) -> dict[str, _Stock]:
        snapshot = _parsed(_snapshot, self._post("availability", product_ids, day))
        return {pid: _Stock(snapshot.source_time, snapshot.items.get(pid)) for pid in product_ids}

    def _post(self, route: str, product_ids: Sequence[str], requested_date: date) -> _Json:
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
            return self._requests.send(lambda: _send(request))
        except (OSError, HTTPException, ValueError) as exc:
            raise _unavailable() from exc


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
        vat_rate=_vat_rate(item),
        comparison_price=_comparison(item),
        valid_from=_helsinki(catalog["validFrom"]).date(),
        valid_to=_helsinki(catalog["validTo"]).date(),
    )


def _vat_rate(item: _Json) -> Decimal | None:
    # A null tax is real data. Reading it as a failure broke the answer for every other product.
    # A missing key or a tax that is not an object is still a broken answer: the subscript
    # raises KeyError or TypeError, which fail closed.
    tax = item["tax"]
    if tax is None or tax["taxRate"] is None:
        return None

    return _not_negative(tax["taxRate"])


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
    sales_unit = first.get("salesUnit")
    return Availability(
        product_id=_text(item["productId"]),
        stock_model=_STOCK_MODELS.get(item.get("logisticModel")),
        # Keep amounts raw for the domain: 999999 or more means unknown stock.
        # A part of a sales unit cannot be ordered, so 2.5 is 2.
        amount=None if amount is None else int(_not_negative(amount)),
        available_date=None if available_date is None else date.fromisoformat(available_date),
        closing_time=None if closing_time is None else _helsinki(closing_time),
        is_sales_blocked=bool(item.get("salesBlock") or first.get("salesBlock")),
        sales_unit=None if sales_unit is None else _text(sales_unit),
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
