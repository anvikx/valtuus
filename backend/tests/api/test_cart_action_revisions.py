import dataclasses
import os
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from app.domain.enums import CartState
from app.main import create_app
from tests.services.test_approval_service import _World

_BASE_URL = "https://junction.anvik.fi"
_AGENT_HEADERS = {"Authorization": f"Bearer {os.environ['AGENT_KEY']}"}
_ACTIONS = ("checkout", "approve", "reject")


def _client(action):
    state = CartState.AUTO if action == "checkout" else CartState.PENDING_APPROVAL
    world = _World(state=state)
    world.cart = dataclasses.replace(world.cart, revision=2)
    world.carts.save(world.cart)
    app = create_app()
    app.state.services = dataclasses.replace(
        app.state.services,
        carts=world.cart_service,
        orders=world.order_service,
        approvals=world.service,
    )
    client = TestClient(app, base_url=_BASE_URL)
    if action != "checkout":
        client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})
    return client, world


def _body(action, revision):
    body = {"revision": revision}
    if action == "reject":
        body["reason"] = "Too much milk."
    return body


def _post(client, world, action, body):
    headers = (
        {**_AGENT_HEADERS, "Idempotency-Key": "checkout-revision-2"} if action == "checkout" else {}
    )
    return client.post(f"/api/v1/carts/{world.cart.cart_id}/{action}", headers=headers, json=body)


@pytest.mark.parametrize("action", _ACTIONS)
@pytest.mark.parametrize("revision", [1, 3], ids=["old", "future"])
def test_revision_mismatch_returns_409_without_changing_cart(action, revision):
    """An action on unseen lines must neither place an order nor record a human decision."""
    client, world = _client(action)
    before = world.carts.get(world.cart.cart_id)
    audit_before = world.steps()

    response = _post(client, world, action, _body(action, revision))

    assert response.status_code == HTTPStatus.CONFLICT
    assert response.json()["error"] == "CONFLICT"
    assert "revision 2" in response.json()["message"]
    assert world.carts.get(world.cart.cart_id) == before
    assert world.orders.by_cart(world.cart.cart_id) is None
    assert world.steps() == audit_before


@pytest.mark.parametrize("action", _ACTIONS)
def test_current_revision_succeeds(action):
    client, world = _client(action)

    response = _post(client, world, action, _body(action, 2))

    assert response.status_code == HTTPStatus.OK
    assert response.json()["revision"] == 2
    expected = CartState.REJECTED if action == "reject" else CartState.ORDERED
    assert world.carts.get(world.cart.cart_id).state is expected


@pytest.mark.parametrize("action", _ACTIONS)
def test_revision_is_required(action):
    client, world = _client(action)
    body = {"reason": "Too much milk."} if action == "reject" else {}

    response = _post(client, world, action, body)

    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert world.carts.get(world.cart.cart_id) == world.cart
    assert world.steps() == []


@pytest.mark.parametrize("action", ("checkout", "approve"))
def test_retry_requires_the_same_revision_even_after_ordering(action):
    client, world = _client(action)
    first = _post(client, world, action, _body(action, 2))

    stale = _post(client, world, action, _body(action, 1))
    retry = _post(client, world, action, _body(action, 2))

    assert stale.status_code == HTTPStatus.CONFLICT
    assert retry.status_code == HTTPStatus.OK
    assert retry.json() == first.json()
    assert len(world.orders.for_day(world.cart.buyer_id, world.cart.lines[0].delivery_date)) == 1


@pytest.mark.parametrize(
    "arguments",
    [
        {"cart_id": "c_1", "revision": 1, "idempotency_key": "k-1"},
        {"cart_id": "c_1", "idempotency_key": "k-1"},
    ],
    ids=["stale", "missing"],
)
def test_mcp_checkout_requires_the_reviewed_revision(arguments, monkeypatch):
    client, world = _client("checkout")
    services = client.app.state.services
    # MCP captures services at app construction, while REST reads app.state.services per call.
    monkeypatch.setattr("app.main._build_services", lambda *args: services)
    with TestClient(create_app(), base_url=_BASE_URL) as client:
        response = client.post(
            "/api/mcp/",
            headers={
                **_AGENT_HEADERS,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "checkout", "arguments": arguments},
            },
        )

    result = response.json()["result"]
    assert result["isError"] is True
    assert "revision" in result["content"][0]["text"]
    if "revision" in arguments:
        assert "CONFLICT" in result["content"][0]["text"]
    assert world.orders.by_cart(world.cart.cart_id) is None
    assert world.carts.get(world.cart.cart_id) == world.cart
