#!/usr/bin/env python3
"""Run 1 and run 2 against the gateway with plain REST calls and no LLM.

It proves that any HTTP client can buy through the gateway, and it is the demo fallback.
Standard library only, so it runs with any Python 3.12 and no install.

    AGENT_KEY=... MAIN_USER_PASSWORD=... python3 scripts/rest_flow.py [--url URL] [--run 1|2]
"""

# The output of this script is its printed trace.
# ruff: noqa: T201

import argparse
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http.client import HTTPException
from http.cookiejar import CookieJar, DefaultCookiePolicy
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, OpenerDirector, Request, build_opener

DEFAULT_URL = "https://junction.anvik.fi"
API_PREFIX = "/api/v1"
TIMEOUT_SECONDS = 60
DAYS_IN_WEEK = 7
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# The http.cookiejar default.
SECURE_PROTOCOLS = ("https", "wss")

STATE_AUTO = "AUTO"
STATE_PENDING = "PENDING_APPROVAL"
STATE_ORDERED = "ORDERED"
SEARCH_READY = "READY"

PRODUCT_QUERY = "milk"
LACTOSE_FREE = "FREE_FROM_LACTOSE"
LITRES = "L"

Json = dict[str, Any]


@dataclass(frozen=True)
class Run:
    number: str
    request_text: str
    litres: int
    expected_state: str


RUNS = (
    Run(
        "1",
        "I need 1,000 litres of lactose-free milk by Monday. Find an option that meets our "
        "requirements based on price and availability.",
        1000,
        STATE_PENDING,
    ),
    Run("2", "20 litres of lactose-free milk for Monday", 20, STATE_AUTO),
)


class FlowError(Exception):
    """A step did not give what the run needs. The message is for the person at the screen."""


def _require_tls(url: str) -> None:
    """The agent key, the password and the session cookie never go over plain http.

    Loopback is the one exception: a local run (make dev-be, make up) has no TLS.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" and parts.hostname not in LOOPBACK_HOSTS:
        raise FlowError(f"{url}: use https. Plain http is allowed only for localhost.")


class Gateway:
    """Agent calls send the agent key. Main user calls send only the session cookie."""

    def __init__(self, url: str, agent_key: str) -> None:
        _require_tls(url)
        self._base = url.rstrip("/") + API_PREFIX
        self._agent_key = agent_key
        # urllib sends the Secure session cookie only over https. Plain http reaches only
        # loopback here, where browsers also send it, so a local run can approve too.
        cookies = CookieJar(DefaultCookiePolicy(secure_protocols=(*SECURE_PROTOCOLS, "http")))
        self._opener: OpenerDirector = build_opener(HTTPCookieProcessor(cookies))

    def agent(self, method: str, path: str, body: Json | None = None) -> Json:
        headers = {"Authorization": f"Bearer {self._agent_key}"}
        if method == "POST":
            # A new key per call: this script never retries, so no call repeats an earlier one.
            headers["Idempotency-Key"] = str(uuid.uuid4())

        return self._call(method, path, body, headers)

    def main_user(self, method: str, path: str, body: Json | None = None) -> Json:
        return self._call(method, path, body, {})

    def _call(self, method: str, path: str, body: Json | None, headers: dict[str, str]) -> Json:
        data = None if body is None else json.dumps(body).encode()
        request = Request(self._base + path, data=data, method=method, headers=headers)
        request.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read()
        except HTTPError as error:
            raise FlowError(_error_text(method, path, error)) from None
        except URLError as error:
            problem = f"{method} {path}: cannot reach the gateway ({error.reason})."
            raise FlowError(problem) from None
        except (OSError, HTTPException) as error:
            # A timeout or a dropped connection after the request went out.
            raise FlowError(f"{method} {path}: no full answer ({error!r}).") from None

        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            # Caddy answers a path outside /api with the web page, so the URL is wrong.
            raise FlowError(f"{method} {path}: the answer is not JSON. Check --url.") from None


def _error_text(method: str, path: str, error: HTTPError) -> str:
    """The gateway error body says what to do next. Show it as it is."""
    try:
        body = json.loads(error.read())
    except ValueError:
        return f"{method} {path}: HTTP {error.code}."

    return (
        f"{method} {path}: HTTP {error.code} {body.get('error')}. {body.get('message')} "
        f"Next step: {body.get('next_step')}"
    )


def next_monday(gateway_now: str) -> date:
    """'Monday' from the gateway clock, not the local one. On a Monday it means next week."""
    today = datetime.fromisoformat(gateway_now).date()
    days_ahead = -today.weekday() % DAYS_IN_WEEK or DAYS_IN_WEEK
    return today + timedelta(days=days_ahead)


def _search(gateway: Gateway, run: Run, deliver_by: date) -> tuple[str, list[str]]:
    """The request_id and the candidate product ids."""
    query = urlencode(
        {
            "query": PRODUCT_QUERY,
            "required_attributes": LACTOSE_FREE,
            "quantity": run.litres,
            "unit": LITRES,
            "deliver_by": deliver_by.isoformat(),
        },
    )
    search = gateway.agent("GET", f"/catalog/search?{query}")
    if search["hint"]["code"] != SEARCH_READY:
        raise FlowError(f"Search hint is {search['hint']['code']}, not READY.")

    product_ids = [candidate["product_id"] for candidate in search["candidates"]]
    print(f"  search {search['request_id']}: {len(product_ids)} candidates")
    return search["request_id"], product_ids


def _offer(
    gateway: Gateway,
    run: Run,
    deliver_by: date,
    request_id: str,
    product_ids: list[str],
) -> Json:
    offer = gateway.agent(
        "POST",
        "/offers",
        {
            # The search request_id, so the cart's audit trail starts at the search.
            "request_id": request_id,
            "product_ids": product_ids,
            "quantity": run.litres,
            "unit": LITRES,
            "deliver_by": deliver_by.isoformat(),
        },
    )
    if not offer["lines"]:
        raise FlowError("The offer has no line for the date.")

    best = offer["lines"][0]
    print(
        f"  offer {offer['offer_id']}: {len(offer['lines'])} ranked, "
        f"{len(offer['rejected'])} not possible",
    )
    for rejected in offer["rejected"]:
        print(f"    not possible: {rejected['product_id']} {rejected['reason_sentence']}")

    print(
        f"  rank 1: {best['product_id']} {best['name']}, {best['unit_price']} {best['currency']} "
        f"per unit, line total {best['line_total']}",
    )
    return offer


def _cart(gateway: Gateway, run: Run, offer: Json) -> Json:
    best = offer["lines"][0]
    line = {
        "offer_id": offer["offer_id"],
        "product_id": best["product_id"],
        "qty": best["sales_units_needed"],
    }
    cart = gateway.agent("POST", "/carts", {"lines": [line], "request_text": run.request_text})
    print(f"  cart {cart['cart_id']}: {cart['state']}, total {cart['total_ex_vat']} ex VAT")
    for sentence in cart["reason_sentences"]:
        print(f"    reason: {sentence}")

    if cart["state"] != run.expected_state:
        raise FlowError(
            f"Cart state is {cart['state']}, but run {run.number} expects {run.expected_state}.",
        )

    return cart


def _approve(gateway: Gateway, cart_id: str, password: str) -> str:
    """The main user approves by REST. The agent then reads the cart, as it does by polling."""
    gateway.main_user("POST", "/auth/login", {"password": password})
    gateway.main_user("POST", f"/carts/{cart_id}/approve")
    print("  approved by the main user")
    cart = gateway.agent("GET", f"/carts/{cart_id}")
    if cart["state"] != STATE_ORDERED:
        raise FlowError(f"After approve the cart is {cart['state']}.")

    return cart["order_id"]


def _allow_auto_orders(gateway: Gateway, password: str) -> None:
    """Automatic orders are off for a new buyer. The main user turns them on, as on the
    permissions page, so a cart within the limits can be ordered with no approval."""
    gateway.main_user("POST", "/auth/login", {"password": password})
    gateway.main_user("PUT", "/mandate", {"can_auto_order": True})
    print("  automatic orders turned on by the main user")


def _place(gateway: Gateway, cart: Json, password: str) -> str:
    if cart["state"] == STATE_AUTO:
        return gateway.agent("POST", f"/carts/{cart['cart_id']}/checkout")["order_id"]

    return _approve(gateway, cart["cart_id"], password)


def run_flow(gateway: Gateway, run: Run, password: str) -> None:
    print(f"Run {run.number}: {run.request_text}")
    mandate = gateway.agent("GET", "/mandate")
    deliver_by = next_monday(mandate["now"])
    if run.expected_state == STATE_AUTO and not mandate["mandate"]["can_auto_order"]:
        _allow_auto_orders(gateway, password)

    print(f"  understood: {run.litres} {LITRES}, lactose free, by {deliver_by.isoformat()}")

    request_id, product_ids = _search(gateway, run, deliver_by)
    offer = _offer(gateway, run, deliver_by, request_id, product_ids)
    cart = _cart(gateway, run, offer)
    order_id = _place(gateway, cart, password)

    order = gateway.agent("GET", f"/orders/{order_id}")
    print(
        f"  order {order['order_id']}: {order['status']}, total {order['total_ex_vat']} "
        f"{order['currency']} ex VAT, approved by {order['approved_by'] or 'nobody'}",
    )


def _secret(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        sys.exit(f"Set {name} in the environment.")

    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL, help="Gateway URL.")
    parser.add_argument("--run", choices=[run.number for run in RUNS], help="One run only.")
    args = parser.parse_args()

    try:
        gateway = Gateway(args.url, _secret("AGENT_KEY"))
    except FlowError as error:
        sys.exit(str(error))

    password = _secret("MAIN_USER_PASSWORD")
    failed = 0
    for run in RUNS:
        if args.run not in (None, run.number):
            continue

        try:
            run_flow(gateway, run, password)
            print(f"Run {run.number}: PASS\n")
        except FlowError as error:
            failed += 1
            print(f"Run {run.number}: FAIL. {error}\n")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
