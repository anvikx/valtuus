import dataclasses
import os

import pytest
from fastapi.testclient import TestClient

from app.domain.cart import LineChange
from app.main import create_app
from app.services.cart_service import CartDetails
from tests.adapters import samples

_BASE_URL = "https://junction.anvik.fi"
_AUTH = {"Authorization": f"Bearer {os.environ['AGENT_KEY']}"}


@pytest.fixture(params=[1, 2], ids=["first-revision", "revised"])
def cart_details(request):
    cart = dataclasses.replace(samples.cart(), revision=request.param)
    changes = () if cart.revision == 1 else (LineChange("p_2", "Oat milk 1 l", 20, 40),)
    return CartDetails(cart, cart.revision, changes)


@pytest.fixture
def application(cart_details, monkeypatch):
    app = create_app()

    def get_details(buyer_id, cart_id):
        assert buyer_id == cart_details.cart.buyer_id
        assert cart_id == cart_details.cart.cart_id
        return cart_details

    monkeypatch.setattr(app.state.services.carts, "get_cart_details", get_details)
    return app


def test_rest_and_mcp_cart_reads_return_the_same_revision_details(application, cart_details):
    with TestClient(application, base_url=_BASE_URL) as client:
        rest = client.get(f"/api/v1/carts/{cart_details.cart.cart_id}", headers=_AUTH)
        mcp = client.post(
            "/api/mcp/",
            headers={
                **_AUTH,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_cart", "arguments": {"cart_id": cart_details.cart.cart_id}},
            },
        )

    rest.raise_for_status()
    assert mcp.json()["result"]["structuredContent"] == rest.json()
    assert rest.json()["revision"] == cart_details.cart.revision
    assert rest.json()["revision_count"] == cart_details.revision_count
    assert rest.json()["changes"] == [dataclasses.asdict(change) for change in cart_details.changes]


def test_main_user_cart_read_includes_history(application, cart_details):
    with TestClient(application, base_url=_BASE_URL) as client:
        client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})

        response = client.get(f"/api/v1/carts/{cart_details.cart.cart_id}")

    response.raise_for_status()
    assert response.json()["revision_count"] == cart_details.revision_count
    assert "changes" in response.json()
