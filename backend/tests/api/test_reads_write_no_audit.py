import dataclasses
import os

import pytest
from fastapi.testclient import TestClient

from app.adapters.memory.repositories import InMemoryMandateRepository, InMemorySearchSetRepository
from app.adapters.signer import NullSigner
from app.domain.audit import AuditRecord
from app.main import create_app
from app.services.decision_waiter import DecisionWaiter
from app.services.offer_service import OfferService
from tests.adapters import samples
from tests.fakes.offer_data import FakeCatalog, FakePriceSource
from tests.services.test_approval_service import _World

_BASE_URL = "https://junction.anvik.fi"
_AUTH = {"Authorization": f"Bearer {os.environ['AGENT_KEY']}"}
_MCP_HEADERS = {
    **_AUTH,
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-06-18",
}
_CANDIDATE_GUARD = 500


@pytest.fixture
def world(monkeypatch):
    world = _World()
    world.approve()
    mandates = InMemoryMandateRepository()
    mandates.add(samples.mandate())
    # create_app(audit=...) puts the mandate, key and session services on the same records.
    base = create_app(audit=world.audit).state.services
    services = dataclasses.replace(
        base,
        carts=world.cart_service,
        decisions=DecisionWaiter(world.cart_service),
        orders=world.order_service,
        approvals=world.service,
        audit=world.audit_service,
        offers=OfferService(
            FakeCatalog(),
            FakePriceSource(),
            world.offers,
            NullSigner(),
            InMemorySearchSetRepository(),
            world.clock,
            world.audit_service,
            world.unit_of_work,
            _CANDIDATE_GUARD,
            mandates,
        ),
    )
    # MCP captures services at app construction, so the world goes in before the build.
    monkeypatch.setattr("app.main._build_services", lambda *args: services)
    return world


@pytest.fixture
def appended(world, monkeypatch):
    records: list[AuditRecord] = []
    append = world.audit.append

    def record(entry: AuditRecord) -> None:
        records.append(entry)
        append(entry)

    monkeypatch.setattr(world.audit, "append", record)
    return records


# Search and get_offers are left out: each writes its SEARCH or OFFER step on purpose.
def _reads(world):
    cart = world.carts.get(world.cart.cart_id)
    return [
        "/api/v1/auth/me",
        "/api/v1/agents",
        "/api/v1/mandate",
        "/api/v1/carts",
        f"/api/v1/carts/{cart.cart_id}",
        f"/api/v1/carts/{cart.cart_id}/wait?revision={cart.revision}",
        f"/api/v1/audit/{cart.cart_id}",
        f"/api/v1/offers/{samples.offer().offer_id}",
        f"/api/v1/orders/{cart.order_id}",
    ]


def _tools(world):
    cart = world.carts.get(world.cart.cart_id)
    return [
        ("get_cart", {"cart_id": cart.cart_id}),
        ("wait_for_decision", {"cart_id": cart.cart_id, "revision": cart.revision}),
        ("get_order", {"order_id": cart.order_id}),
        ("get_mandate", {}),
        ("get_audit", {"cart_id": cart.cart_id}),
    ]


def _call_tool(client, name, arguments):
    response = client.post(
        "/api/mcp/",
        headers=_MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    return response.json()["result"]


def test_rest_reads_write_no_audit_record(world, appended):
    """The record is the order story. A page or agent poll that wrote to it would bury the
    decisions under read noise, and the audit page would grow on each refresh."""
    with TestClient(create_app(), base_url=_BASE_URL) as client:
        client.post("/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]})
        appended.clear()

        statuses = {path: client.get(path).status_code for path in _reads(world)}

    assert statuses == dict.fromkeys(_reads(world), 200)
    assert appended == []


def test_mcp_reads_write_no_audit_record(world, appended):
    """The agent door reads the same services, so its polls must stay out of the record too."""
    with TestClient(create_app(), base_url=_BASE_URL) as client:
        appended.clear()

        results = {name: _call_tool(client, name, args) for name, args in _tools(world)}

    assert {
        name: result.get("isError", False) for name, result in results.items()
    } == dict.fromkeys(results, False)
    assert appended == []
