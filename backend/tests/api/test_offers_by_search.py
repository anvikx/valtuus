"""get_offers by request_id: an empty product_ids is valid, a call with neither is not."""

import dataclasses
import os

from fastapi.testclient import TestClient

from app.main import create_app
from tests.adapters import samples

_BASE_URL = "https://junction.anvik.fi"
_REQUEST_ID = "r_0123456789abcdef0123456789abcdef"
_AUTH = {"Authorization": f"Bearer {os.environ['AGENT_KEY']}"}
_MCP_HEADERS = {
    **_AUTH,
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}


class _RecordingOffers:
    def __init__(self) -> None:
        self.queries = []

    def get_offers(self, agent, query):
        self.queries.append(query)
        return samples.offer()


def test_rest_offer_with_no_product_ids_and_no_request_id_is_invalid():
    """Nothing to price is a caller mistake, so it must fail at the edge with a clear code."""
    with TestClient(create_app(), base_url=_BASE_URL) as client:
        response = client.post("/api/v1/offers", headers=_AUTH, json={"quantity": 1})

    assert response.status_code == 422
    assert response.json()["error"] == "VALIDATION_ERROR"


def test_mcp_get_offers_takes_a_request_id_alone(monkeypatch):
    """The agent prices the whole search without copying hundreds of ids."""
    offers = _RecordingOffers()
    services = dataclasses.replace(create_app().state.services, offers=offers)
    monkeypatch.setattr("app.main._build_services", lambda *args: services)

    with TestClient(create_app(), base_url=_BASE_URL) as client:
        response = client.post(
            "/api/mcp/",
            headers=_MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_offers",
                    "arguments": {"request": {"request_id": _REQUEST_ID}},
                },
            },
        )

    assert response.json()["result"].get("isError") is not True
    (query,) = offers.queries
    assert query.product_ids == ()
    assert query.request_id == _REQUEST_ID
