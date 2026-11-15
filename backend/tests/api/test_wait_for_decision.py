import dataclasses
import os
import time
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from app.domain.enums import CartState
from app.main import create_app
from app.services.decision_waiter import DecisionWaiter
from tests.services.test_approval_service import _World

_BASE_URL = "https://junction.anvik.fi"
_AUTH = {"Authorization": f"Bearer {os.environ['AGENT_KEY']}"}
_MCP_HEADERS = {
    **_AUTH,
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}
# Short hold: the door test checks the wiring, the service test checks the timing.
_HOLD_SECONDS = 0.2


@pytest.fixture
def world(monkeypatch):
    world = _World()
    world.deny.is_on = True
    app = create_app()
    services = dataclasses.replace(
        app.state.services,
        carts=world.cart_service,
        decisions=DecisionWaiter(world.cart_service, _HOLD_SECONDS, _HOLD_SECONDS / 5),
    )
    # MCP captures services at app construction, so the world goes in before the build.
    monkeypatch.setattr("app.main._build_services", lambda *args: services)
    return world


def _mcp_wait(client, cart_id, revision):
    response = client.post(
        "/api/mcp/",
        headers=_MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "wait_for_decision",
                "arguments": {"cart_id": cart_id, "revision": revision},
            },
        },
    )
    return response.json()["result"]


def test_rest_and_mcp_wait_return_the_same_pending_cart(world):
    """Both doors must answer alike, so an agent on either one reads the same cart."""
    cart = world.cart

    with TestClient(create_app(), base_url=_BASE_URL) as client:
        started = time.monotonic()
        rest = client.get(
            f"/api/v1/carts/{cart.cart_id}/wait",
            params={"revision": cart.revision},
            headers=_AUTH,
        )
        held = time.monotonic() - started
        mcp = _mcp_wait(client, cart.cart_id, cart.revision)

    rest.raise_for_status()
    # A door that read once instead of waiting would send the agent back into a tight loop.
    assert held >= _HOLD_SECONDS
    assert rest.json()["state"] == CartState.PENDING_APPROVAL
    assert mcp.get("isError") is not True
    assert mcp["structuredContent"] == rest.json()
    assert "wait_for_decision" in rest.json()["next_step"]


def test_wait_on_an_unknown_cart_gives_the_not_found_body(world):
    """The agent must get the gateway error body, not a held call that ends in a timeout."""
    with TestClient(create_app(), base_url=_BASE_URL) as client:
        rest = client.get("/api/v1/carts/c_missing/wait", params={"revision": 1}, headers=_AUTH)
        mcp = _mcp_wait(client, "c_missing", 1)

    assert rest.status_code == HTTPStatus.NOT_FOUND
    assert rest.json()["error"] == "NOT_FOUND"
    assert mcp["isError"] is True
    assert "NOT_FOUND" in mcp["content"][0]["text"]
