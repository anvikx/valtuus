"""Pins the routes, auth and tools while the services are stubs, so each part builds behind them."""

import dataclasses
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from http import HTTPStatus

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.adapters.memory.repositories import InMemoryAgentKeyRepository, InMemoryOrderRepository
from app.domain.agent_key import hash_agent_key
from app.domain.audit import AuditRecord
from app.domain.enums import AgentKeyStatus, AuditStep, ReasonCode
from app.domain.order import Order
from app.main import create_app

_BASE_URL = "https://junction.anvik.fi"
_AGENT_KEY = os.environ["AGENT_KEY"]
_AUTH = {"Authorization": f"Bearer {_AGENT_KEY}"}
_IDEMPOTENCY = {"Idempotency-Key": "k-1"}
_AUDIT_PATH = "/api/v1/audit/c_1"
_CART = {
    "lines": [{"offer_id": "o_1", "product_id": "p_1", "qty": 1}],
    "request_text": "milk for Monday",
}

# The agent skill and the frontend call these paths.
_CONTRACT = {
    ("GET", "/api/v1/catalog/search"),
    ("POST", "/api/v1/offers"),
    ("POST", "/api/v1/carts"),
    ("GET", "/api/v1/carts"),
    ("GET", "/api/v1/carts/{cart_id}"),
    ("POST", "/api/v1/carts/{cart_id}/checkout"),
    ("POST", "/api/v1/carts/{cart_id}/approve"),
    ("POST", "/api/v1/carts/{cart_id}/reject"),
    ("GET", "/api/v1/orders/{order_id}"),
    ("GET", "/api/v1/mandate"),
    ("PUT", "/api/v1/mandate"),
    ("GET", "/api/v1/agents"),
    ("GET", "/api/v1/audit/{cart_id}"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("GET", "/api/v1/auth/me"),
}
_AGENT_TOOLS = {
    "ping",
    "search_products",
    "get_offers",
    "create_cart",
    "get_cart",
    "checkout",
    "get_order",
    "get_mandate",
    "get_audit",
}
# One call per route that only an agent key opens: (method, path, extra headers, JSON body).
_AGENT_ONLY_CALLS = [
    ("GET", "/api/v1/catalog/search?query=milk", {}, None),
    ("POST", "/api/v1/offers", {}, {"product_ids": ["p_1"]}),
    ("POST", "/api/v1/carts", _IDEMPOTENCY, _CART),
    ("POST", "/api/v1/carts/c_1/checkout", _IDEMPOTENCY, None),
    ("GET", "/api/v1/mandate", {}, None),
    ("GET", _AUDIT_PATH, {}, None),
]
# The agent polls these and the main user opens them on the approve and order pages.
_SHARED_READS = [
    ("GET", "/api/v1/carts/c_1", {}, None),
    ("GET", "/api/v1/orders/o_1", {}, None),
]
_AGENT_CALLS = _AGENT_ONLY_CALLS + _SHARED_READS
_OFFERS_PATH = "/api/v1/offers"
_CARTS_PATH = "/api/v1/carts"
_MANDATE_PATH = "/api/v1/mandate"
_LIVE_PATHS = {
    _OFFERS_PATH,
    _CARTS_PATH,
    "/api/v1/carts/c_1",
    "/api/v1/carts/c_1/checkout",
    "/api/v1/orders/o_1",
    _MANDATE_PATH,
    _AUDIT_PATH,
    "/api/v1/catalog/search?query=milk",
}
_STUB_CALLS = [call for call in _AGENT_CALLS if call[1] not in _LIVE_PATHS]
# A person must do these. An agent key that tries one is refused and recorded.
_HUMAN_ACTIONS = [
    ("POST", "/api/v1/carts/c_1/approve", None),
    ("POST", "/api/v1/carts/c_1/reject", {"reason": "too much"}),
    ("PUT", "/api/v1/mandate", {"max_auto_order_value": "300.00"}),
]
_MAIN_USER_READS = [
    ("GET", "/api/v1/agents", None),
    ("GET", _CARTS_PATH, None),
    ("GET", "/api/v1/auth/me", None),
]


class _Records:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)

    def for_cart(self, cart_id: str) -> list[AuditRecord]:
        return [record for record in self.records if record.cart_id == cart_id]


def _client(app: FastAPI | None = None) -> TestClient:
    return TestClient(app or create_app(), base_url=_BASE_URL)


def _strip_scopes(agent_keys: InMemoryAgentKeyRepository) -> None:
    seeded = agent_keys.by_hash(hash_agent_key(_AGENT_KEY))
    agent_keys.add(dataclasses.replace(seeded, scopes=frozenset()))


def test_routes_match_the_contract() -> None:
    """The agent skill and the frontend are written against these paths."""
    # FastAPI 0.162 hides included routes from app.routes, so read the OpenAPI paths.
    paths = create_app().openapi()["paths"]
    routes = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/v1/")
        for method in operations
    }

    assert routes == _CONTRACT


@pytest.mark.parametrize(("method", "path", "headers", "body"), _AGENT_ONLY_CALLS)
def test_agent_route_without_key_is_refused(method, path, headers, body) -> None:
    """Without the check, anyone who knows the URL could order as hotel 1."""
    response = _client().request(method, path, headers=headers, json=body)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(("method", "path", "headers", "body"), _AGENT_CALLS)
def test_agent_route_without_scope_is_forbidden(
    method, path, headers, body, agent_keys: InMemoryAgentKeyRepository
) -> None:
    """A key limited to some scopes must not reach the others."""
    app = create_app(agent_keys=agent_keys)
    _strip_scopes(agent_keys)

    response = _client(app).request(method, path, headers={**_AUTH, **headers}, json=body)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"] == "FORBIDDEN"


@pytest.mark.parametrize(("method", "path", "headers", "body"), _STUB_CALLS)
def test_agent_route_reaches_its_service(method, path, headers, body) -> None:
    """501 means auth and validation passed and the stub service ran."""
    # TODO: expect the real status codes when the services land, and remove this test then.
    response = _client().request(method, path, headers={**_AUTH, **headers}, json=body)

    assert response.status_code == HTTPStatus.NOT_IMPLEMENTED


def test_mandate_answers_with_rules_and_gateway_time() -> None:
    """The agent plans from these rules and resolves "Monday" from the gateway time."""
    response = _client().get(_MANDATE_PATH, headers=_AUTH)

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["mandate"]["version"] == 1
    assert body["mandate"]["summary"][0].startswith("This agent may place orders up to")
    assert body["timezone"] == "Europe/Helsinki"
    assert datetime.fromisoformat(body["now"]).utcoffset() is not None


def test_audit_of_an_unknown_cart_is_not_found() -> None:
    """The agent learns the cart id is wrong, not that the cart has an empty history."""
    response = _client().get(_AUDIT_PATH, headers=_AUTH)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"] == "NOT_FOUND"


def test_main_user_raise_reaches_the_agent() -> None:
    """The agent reads the raised limit on its next call, so a waiting cart can go AUTO."""
    client = _client()
    client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})

    response = client.put(_MANDATE_PATH, json={"max_auto_order_value": "1500.00"})

    assert response.status_code == HTTPStatus.OK
    assert response.json()["mandate"]["version"] == 2
    agent_view = client.get(_MANDATE_PATH, headers=_AUTH).json()["mandate"]
    assert agent_view["version"] == 2
    assert Decimal(agent_view["max_auto_order_value"]) == Decimal(1500)


def test_main_user_inbox_lists_the_buyers_carts() -> None:
    """The approval inbox opens on this list, so a new main user sees an empty inbox, not 501."""
    client = _client()
    client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})

    response = client.get(_CARTS_PATH)

    assert response.status_code == HTTPStatus.OK
    assert response.json() == []


def test_main_user_sees_the_agent_without_its_key() -> None:
    """The page shows who may buy, but a leaked key or hash would let anyone buy as the agent."""
    client = _client()
    client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})

    response = client.get("/api/v1/agents")

    assert response.status_code == HTTPStatus.OK
    [agent] = response.json()
    assert agent["status"] == AgentKeyStatus.ACTIVE
    assert "key_hash" not in agent
    assert _AGENT_KEY not in response.text
    assert hash_agent_key(_AGENT_KEY) not in response.text


def test_offers_answer_with_a_stored_offer() -> None:
    """The test catalog is empty, so the id is rejected and no Valio call is made."""
    response = _client().post(_OFFERS_PATH, headers=_AUTH, json={"product_ids": ["p_1"]})

    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["offer_id"].startswith("o_")
    assert body["lines"] == []
    assert body["rejected"][0]["reason_code"] == "PRODUCT_NOT_FOUND"


def test_a_made_up_request_id_is_a_validation_error() -> None:
    """A guessable id could join this offer to another buyer's search in the audit."""
    body = {"product_ids": ["p_1"], "request_id": "r_1"}

    response = _client().post(_OFFERS_PATH, headers=_AUTH, json=body)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("quantity", ["1000001", "1e27"])
def test_a_huge_quantity_is_a_validation_error(quantity) -> None:
    """1e27 L overflowed the cent rounding of the line total and answered 500."""
    body = {"product_ids": ["p_1"], "quantity": quantity, "unit": "L"}

    response = _client().post(_OFFERS_PATH, headers=_AUTH, json=body)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"] == "VALIDATION_ERROR"


@pytest.mark.parametrize("qty", [1_000_001, 10**27])
def test_a_huge_cart_qty_is_a_validation_error(qty) -> None:
    """The cart line total uses the same cent rounding, so it would overflow into a 500 too."""
    lines = [{**_CART["lines"][0], "qty": qty}]

    response = _client().post(
        "/api/v1/carts",
        headers={**_AUTH, **_IDEMPOTENCY},
        json={**_CART, "lines": lines},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(("method", "path", "body"), _MAIN_USER_READS)
def test_agent_key_does_not_open_main_user_route(method, path, body) -> None:
    """An agent key is not a session, so the main user's own pages stay closed to it."""
    response = _client().request(method, path, headers=_AUTH, json=body)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["error"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(("method", "path", "body"), _HUMAN_ACTIONS)
def test_agent_key_on_human_action_is_refused_and_recorded(method, path, body) -> None:
    """An agent that tries to approve its own cart is stopped, and the main user sees the try."""
    audit = _Records()

    response = _client(create_app(audit=audit)).request(method, path, headers=_AUTH, json=body)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert response.json()["error"] == "FORBIDDEN"
    [record] = audit.records
    assert record.step is AuditStep.REFUSED
    assert record.reason_codes == (ReasonCode.HUMAN_SESSION_REQUIRED,)
    assert record.input_data == {"method": method, "path": path}


def test_dead_session_cookie_does_not_hide_the_agent_try() -> None:
    """An agent that sends a junk cookie with its key is still refused on the record."""
    audit = _Records()
    client = _client(create_app(audit=audit))
    client.cookies.set("valtuus_session", "not-a-session")

    response = client.post("/api/v1/carts/c_1/approve", headers=_AUTH)

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert [record.step for record in audit.records] == [AuditStep.REFUSED]


@pytest.mark.parametrize(("method", "path", "body"), _HUMAN_ACTIONS)
def test_unknown_key_on_human_action_is_unauthenticated(method, path, body) -> None:
    """A wrong key proves nothing about the caller, so it gets 401 and writes no record."""
    audit = _Records()

    response = _client(create_app(audit=audit)).request(
        method,
        path,
        headers={"Authorization": "Bearer not-a-key"},
        json=body,
    )

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response.json()["error"] == "UNAUTHENTICATED"
    assert audit.records == []


@pytest.mark.parametrize(("method", "path", "body"), _HUMAN_ACTIONS)
def test_revoked_key_on_human_action_is_unauthenticated(
    method, path, body, agent_keys: InMemoryAgentKeyRepository
) -> None:
    """A revoked agent no longer acts for the buyer, so its tries do not fill the buyer's log."""
    audit = _Records()
    app = create_app(agent_keys=agent_keys, audit=audit)
    seeded = agent_keys.by_hash(hash_agent_key(_AGENT_KEY))
    agent_keys.add(dataclasses.replace(seeded, status=AgentKeyStatus.REVOKED))

    response = _client(app).request(method, path, headers=_AUTH, json=body)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert audit.records == []


@pytest.mark.parametrize(("method", "path", "body"), _HUMAN_ACTIONS)
def test_session_opens_human_action(method, path, body) -> None:
    """The browser of the main user may also send a key, so the session decides first."""
    client = _client()
    client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})

    response = client.request(method, path, headers=_AUTH, json=body)

    # The service answers (a stub 501, or 404 for the made up cart): the door let it through.
    assert response.status_code not in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}


@pytest.mark.parametrize(("method", "path", "headers", "body"), _SHARED_READS)
def test_shared_read_without_key_goes_to_the_session(method, path, headers, body) -> None:
    """The main user has no agent key, so no Bearer header means the session decides."""
    client = _client()

    refused = client.request(method, path, headers=headers, json=body)
    client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})
    allowed = client.request(method, path, headers=headers, json=body)

    assert refused.status_code == HTTPStatus.UNAUTHORIZED
    # Not 401: the session check passed and the service ran (404 for c_1, 501 for a stub).
    assert allowed.status_code in (HTTPStatus.NOT_FOUND, HTTPStatus.NOT_IMPLEMENTED)


def test_cart_for_an_unknown_offer_is_not_found() -> None:
    """The test store has no offer o_1, so the cart cannot be priced."""
    response = _client().post(_CARTS_PATH, headers={**_AUTH, **_IDEMPOTENCY}, json=_CART)

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json()["error"] == "NOT_FOUND"


def test_unknown_field_is_a_validation_error() -> None:
    """An agent must not slip a price into a cart."""
    lines = [{**_CART["lines"][0], "unit_price": "0.01"}]
    response = _client().post(
        "/api/v1/carts",
        headers={**_AUTH, **_IDEMPOTENCY},
        json={**_CART, "lines": lines},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"] == "VALIDATION_ERROR"


def test_cart_without_idempotency_key_is_refused() -> None:
    """A retried create_cart without the key would make a second cart."""
    response = _client().post("/api/v1/carts", headers=_AUTH, json=_CART)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def test_cart_with_empty_idempotency_key_is_refused() -> None:
    """An empty key would match every other empty key and replay the wrong cart."""
    response = _client().post(
        "/api/v1/carts",
        headers={**_AUTH, "Idempotency-Key": ""},
        json=_CART,
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


def _mcp(app: FastAPI, method: str, params: dict[str, object]) -> dict[str, object]:
    with _client(app) as client:
        response = client.post(
            "/api/mcp/",
            headers={
                **_AUTH,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )

    return response.json()["result"]


def test_mcp_lists_one_tool_per_agent_operation() -> None:
    result = _mcp(create_app(), "tools/list", {})

    assert {tool["name"] for tool in result["tools"]} == _AGENT_TOOLS


def test_mcp_tool_without_scope_is_forbidden(agent_keys: InMemoryAgentKeyRepository) -> None:
    """Both doors run one scope check, so MCP cannot open what REST refuses."""
    app = create_app(agent_keys=agent_keys)
    _strip_scopes(agent_keys)

    result = _mcp(app, "tools/call", {"name": "get_mandate", "arguments": {}})

    assert result["isError"] is True
    assert '"error":"FORBIDDEN"' in result["content"][0]["text"]


def test_mcp_cart_with_empty_idempotency_key_is_refused() -> None:
    """Both doors use one key type, so MCP cannot take what REST refuses."""
    arguments = {"request": _CART, "idempotency_key": ""}
    result = _mcp(create_app(), "tools/call", {"name": "create_cart", "arguments": arguments})

    assert result["isError"] is True
    assert "idempotency_key" in result["content"][0]["text"]


def _order(order_id: str, cart_id: str) -> Order:
    return Order(
        order_id=order_id,
        cart_id=cart_id,
        buyer_id="hotel-1",
        lines=(),
        total_ex_vat=Decimal("0.00"),
        currency="EUR",
        placed_at=datetime(2026, 11, 14, tzinfo=UTC),
        placed_by="claude-code",
        approved_by=None,
        offer_ids=(),
        mandate_version=1,
        issuer="valtuus",
        signature=None,
    )


def test_second_order_for_one_cart_is_refused() -> None:
    """Checkout and approve can race on one cart. Only one order may come out."""
    orders = InMemoryOrderRepository()
    orders.add(_order("o_1", "c_1"))

    with pytest.raises(ValueError, match="has an order"):
        orders.add(_order("o_2", "c_1"))

    assert orders.by_cart("c_1").order_id == "o_1"
    assert orders.for_day("hotel-1", date(2026, 11, 16)) == []


def test_search_tool_lists_valid_attributes():
    from app.domain.catalog_search import VALID_ATTRIBUTES

    result = _mcp(create_app(), "tools/list", {})
    tool = next(tool for tool in result["tools"] if tool["name"] == "search_products")

    assert all(code in tool["description"] for code in VALID_ATTRIBUTES)


def test_search_tool_schema_lists_valid_attributes():
    """An agent reads the input schema, so a wrong code is caught before the call is sent."""
    from app.domain.catalog_search import VALID_ATTRIBUTES

    result = _mcp(create_app(), "tools/list", {})
    tool = next(tool for tool in result["tools"] if tool["name"] == "search_products")
    request = tool["inputSchema"]["$defs"]["SearchRequest"]

    assert request["properties"]["required_attributes"]["items"]["enum"] == list(VALID_ATTRIBUTES)


@pytest.mark.parametrize(
    "search_input", [{"query": "ab"}, {"query": "milk", "required_attributes": ["ORGANIC"]}]
)
def test_search_validation_matches_rest_and_mcp(search_input):
    app = create_app()
    response = _client(app).get("/api/v1/catalog/search", headers=_AUTH, params=search_input)
    result = _mcp(
        app,
        "tools/call",
        {"name": "search_products", "arguments": {"request": search_input}},
    )

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["error"] == "VALIDATION_ERROR"
    assert result["isError"]
    assert "VALIDATION_ERROR" in result["content"][0]["text"]


def test_search_returns_empty_result_and_one_record():
    records = _Records()
    response = _client(create_app(audit=records)).get(
        "/api/v1/catalog/search",
        headers=_AUTH,
        params={"query": "xyzzy"},
    )

    assert response.status_code == HTTPStatus.OK
    assert response.json()["candidates"] == []
    assert response.json()["status"] == "NO_MATCH"
    assert len(records.records) == 1
    assert records.records[0].step == AuditStep.SEARCH
