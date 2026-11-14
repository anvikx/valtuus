"""REST and MCP expose the same S2 results with one SEARCH record per call."""

import os
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.adapters.memory.repositories import InMemoryMandateRepository
from app.adapters.product_store import ProductStore
from app.domain.catalog import Allergens
from app.domain.enums import AllergenStatus, Decision
from app.main import create_app
from tests.adapters.samples import mandate
from tests.fakes.catalog import Records, item

_FIELDS = {
    "understood",
    "candidates",
    "total_hits",
    "categories",
    "hint",
    "hint_category",
    "excluded",
    "missing_fields",
    "request_id",
}


@pytest.mark.parametrize(
    "expected", ["READY", "NO_MATCH", "EXCLUDED_ONLY", "MISSING_FIELDS", "GUARD_CUT"]
)
@pytest.mark.parametrize("mcp_url", ["/api/mcp", "/api/mcp/"])
def test_rest_and_mcp_match_and_write_one_search_each(monkeypatch, expected, mcp_url):
    products = [item("1", category="1"), item("2", category="2")]
    if expected == "NO_MATCH":
        products = []
    elif expected == "EXCLUDED_ONLY":
        products = [item(allergens=Allergens(AllergenStatus.UNKNOWN, ()))]
    elif expected == "GUARD_CUT":
        products = [item(str(i)) for i in range(501)]
    policy = replace(mandate(), required_attributes=(), allergen_unknown_policy=Decision.DENY)
    monkeypatch.setattr(InMemoryMandateRepository, "latest", lambda self, buyer: policy)
    monkeypatch.setattr(ProductStore, "search_names", lambda self, query: products)
    records = Records()
    app = create_app(audit=records)
    request = {"query": "MILK", "unit": "L", "deliver_by": "2026-11-16"}
    if expected != "MISSING_FIELDS":
        request["quantity"] = 10
    auth = {"Authorization": f"Bearer {os.environ['AGENT_KEY']}"}

    with TestClient(app, base_url="https://junction.anvik.fi") as client:
        rest = client.get("/api/v1/catalog/search", headers=auth, params=request)
        assert rest.status_code == 200
        assert len(records.records) == 1
        rpc = client.post(
            mcp_url,
            follow_redirects=False,
            headers={
                **auth,
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "search_products",
                    "arguments": {"request": request},
                },
            },
        )

    assert rpc.status_code == 200
    body = rest.json()
    tool_body = rpc.json()["result"]["structuredContent"]
    assert set(body) == set(tool_body) == _FIELDS
    assert body["hint"]["code"] == tool_body["hint"]["code"] == expected
    assert body["understood"]["query"] == "milk"
    assert body["understood"]["category"] is None
    assert all(
        set(category) == {"category", "hits", "examples", "in_list"}
        for category in body["categories"]
    )
    flags = {category["category"]: category["in_list"] for category in body["categories"]}
    if expected in ("READY", "MISSING_FIELDS"):
        assert flags == {"1": True, "2": False}
    elif expected == "GUARD_CUT":
        assert flags == {"10400": True}
    else:
        assert flags == {}
    assert body.pop("request_id") == records.records[0].request_id
    assert tool_body.pop("request_id") == records.records[1].request_id
    assert body == tool_body
    assert len(records.records) == 2
    assert all(record.step == "SEARCH" for record in records.records)
