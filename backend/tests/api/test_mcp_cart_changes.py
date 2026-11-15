import dataclasses
import os

import pytest
from fastapi.testclient import TestClient

from app.domain.enums import CartState
from app.main import create_app
from tests.services.test_approval_service import _World

_BASE_URL = "https://junction.anvik.fi"
_HEADERS = {
    "Authorization": f"Bearer {os.environ['AGENT_KEY']}",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


def _call(world, monkeypatch, tool, arguments):
    app = create_app()
    services = dataclasses.replace(app.state.services, carts=world.cart_service)
    # MCP captures services at app construction, so the world goes in before the build.
    monkeypatch.setattr("app.main._build_services", lambda *args: services)
    with TestClient(create_app(), base_url=_BASE_URL) as client:
        response = client.post(
            "/api/mcp/",
            headers=_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool, "arguments": arguments},
            },
        )

    return response.json()["result"]


@pytest.mark.parametrize("state", [CartState.AUTO, CartState.PENDING_APPROVAL])
def test_mcp_withdraw_ends_the_open_cart(state, monkeypatch):
    """The buyer cancels through the agent, so the main user can no longer approve it."""
    world = _World(state=state)

    result = _call(world, monkeypatch, "withdraw_cart", {"cart_id": world.cart.cart_id})

    assert result.get("isError") is not True
    assert result["structuredContent"]["state"] == CartState.WITHDRAWN
    assert world.carts.get(world.cart.cart_id).state is CartState.WITHDRAWN


def test_mcp_revise_makes_the_next_revision(monkeypatch):
    """A changed request must change the open cart, not leave a second cart to approve."""
    world = _World()
    line = world.cart.lines[0]
    arguments = {
        "cart_id": world.cart.cart_id,
        "idempotency_key": "revise-1",
        "request": {
            "base_revision": world.cart.revision,
            "lines": [{"offer_id": line.offer_id, "product_id": line.product_id, "qty": 1}],
            "request_text": "make it 1",
        },
    }

    result = _call(world, monkeypatch, "revise_cart", arguments)

    assert result.get("isError") is not True
    stored = world.carts.get(world.cart.cart_id)
    assert stored.revision == world.cart.revision + 1
    assert stored.lines[0].qty == 1
    assert result["structuredContent"]["revision"] == stored.revision
