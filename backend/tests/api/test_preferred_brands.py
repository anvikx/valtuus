import base64
import os
from dataclasses import replace
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.adapters.clock import FixedClock
from app.adapters.product_store import ProductStore
from app.config import Settings
from app.main import create_app
from tests.fakes.offer_data import MILK_ID, NOW, FakePriceSource, price, product, stock

_ARLA_ID = "469363"
_BASE_URL = "https://junction.anvik.fi"
_AUTH = {"Authorization": f"Bearer {os.environ['AGENT_KEY']}"}
_REQUEST = "1,000 litres of lactose free milk by Monday"


@pytest.fixture
def client(monkeypatch, request):
    products = {
        MILK_ID: replace(product(), names={"en": "Milk"}, attributes=("FREE_FROM_LACTOSE",)),
        _ARLA_ID: replace(
            product(_ARLA_ID),
            names={"en": "Milk"},
            brand="Arla",
            attributes=("FREE_FROM_LACTOSE",),
        ),
    }
    source = FakePriceSource(
        [price(), price(_ARLA_ID, "1.50")],
        [stock(), stock(_ARLA_ID, amount=getattr(request, "param", 2000))],
    )
    monkeypatch.setattr(ProductStore, "get", lambda self, pid: products.get(pid))
    monkeypatch.setattr(ProductStore, "search_names", lambda self, query: tuple(products.values()))
    monkeypatch.setattr("app.main.ValioClient", lambda *args: source)
    monkeypatch.setattr("app.main.SystemClock", lambda: FixedClock(NOW))
    settings = Settings(signing_private_key=SecretStr(base64.b64encode(bytes(range(32))).decode()))
    with TestClient(create_app(settings), base_url=_BASE_URL) as client:
        _login(client)
        saved = client.put(
            "/api/v1/mandate",
            json={
                "preferred_brands": ["Arla"],
                "can_auto_order": True,
                "max_auto_order_value": "5000.00",
                "max_auto_value_per_delivery_date": "5000.00",
            },
        )
        assert saved.status_code == HTTPStatus.OK
        assert saved.json()["mandate"]["preferred_brands"] == ["Arla"]
        client.post("/api/v1/auth/logout")
        yield client


def _login(client):
    response = client.post(
        "/api/v1/auth/login", json={"password": os.environ["MAIN_USER_PASSWORD"]}
    )
    assert response.status_code == HTTPStatus.NO_CONTENT


def _call(client, transport, tool, request, *, key=None):
    if transport == "mcp":
        arguments = {"request": request}
        if key is not None:
            arguments["idempotency_key"] = key
        response = client.post(
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
                "params": {"name": tool, "arguments": arguments},
            },
        )
        assert response.status_code == HTTPStatus.OK
        result = response.json()["result"]
        assert result.get("isError") is not True
        return result["structuredContent"]
    if tool == "search_products":
        response = client.get("/api/v1/catalog/search", headers=_AUTH, params=request)
    else:
        path = "/api/v1/offers" if tool == "get_offers" else "/api/v1/carts"
        headers = _AUTH if key is None else {**_AUTH, "Idempotency-Key": key}
        response = client.post(path, headers=headers, json=request)
    assert response.status_code == HTTPStatus.OK
    return response.json()


def _milk_offers(client, transport):
    search = _call(
        client,
        transport,
        "search_products",
        {
            "query": "milk",
            "quantity": 1000,
            "unit": "L",
            "deliver_by": "2026-11-16",
            "required_attributes": ["FREE_FROM_LACTOSE"],
        },
    )
    assert search["hint"]["code"] == "READY"
    return _call(
        client,
        transport,
        "get_offers",
        {
            "product_ids": [p["product_id"] for p in search["candidates"]],
            "request_id": search["request_id"],
            "quantity": 1000,
            "unit": "L",
            "deliver_by": "2026-11-16",
        },
    )


@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_mandate_brand_has_priority(client, transport):
    """Among stocked products the permissions-page preference outranks a cheaper brand."""
    offer = _milk_offers(client, transport)

    assert [line["brand"] for line in offer["lines"]] == ["Arla", "Valio"]
    assert offer["lines"][0]["unit_price"] == "1.50"
    assert offer["lines"][1]["unit_price"] == "1.01"
    verified = client.post("/api/v1/verify", json={"jws": offer["signature"], "body": offer})
    assert verified.json()["valid"] is True
    assert verified.json()["body_matches"] is True
    cart = _call(
        client,
        transport,
        "create_cart",
        {
            "lines": [
                {
                    "offer_id": offer["offer_id"],
                    "product_id": MILK_ID,
                    "qty": 1000,
                }
            ],
            "request_text": _REQUEST,
        },
        key="nonpreferred-brand",
    )
    assert cart["state"] == "PENDING_APPROVAL"
    assert cart["decision"] == "HUMAN"
    assert "SUBSTITUTE_OUTSIDE_PREFERENCE" in cart["reason_codes"]
    assert "OVER_AUTO_LIMIT" not in cart["reason_codes"]
    assert cart["approve_url"]
    assert cart["order_id"] is None
    checkout = client.post(
        f"/api/v1/carts/{cart['cart_id']}/checkout",
        headers={**_AUTH, "Idempotency-Key": "nonpreferred-checkout"},
        json={"revision": cart["revision"]},
    )
    assert checkout.status_code == HTTPStatus.CONFLICT


@pytest.mark.parametrize("client", [384], indirect=True)
@pytest.mark.parametrize("transport", ["rest", "mcp"])
def test_rank_one_cart_is_not_denied(client, transport):
    """Rule 18's normal path takes full-stock Valio when preferred Arla only has 384 L."""
    offer = _milk_offers(client, transport)
    best, partial = offer["lines"]
    assert best["product_id"] == MILK_ID
    assert best["rank"] == 1
    assert best["tier"] == "BEST"
    assert partial["product_id"] == _ARLA_ID
    assert partial["available_qty"] == 384
    assert partial["sales_units_needed"] == 1000

    cart = _call(
        client,
        transport,
        "create_cart",
        {
            "lines": [
                {
                    "offer_id": offer["offer_id"],
                    "product_id": best["product_id"],
                    "qty": best["sales_units_needed"],
                }
            ],
            "request_text": _REQUEST,
        },
        key="rank-one-cart",
    )

    assert cart["state"] == "PENDING_APPROVAL"
    assert cart["decision"] == "HUMAN"
    assert cart["lines"][0]["qty"] == 1000
    assert "SUBSTITUTE_OUTSIDE_PREFERENCE" in cart["reason_codes"]
    assert "PARTIAL_AVAILABILITY" not in cart["reason_codes"]
    assert cart["approve_url"]
    assert cart["order_id"] is None


def test_empty_list_clears_preference(client):
    _login(client)

    saved = client.put("/api/v1/mandate", json={"preferred_brands": []})

    assert saved.status_code == HTTPStatus.OK
    assert saved.json()["mandate"]["preferred_brands"] == []
    client.post("/api/v1/auth/logout")
    offer = _call(
        client,
        "rest",
        "get_offers",
        {
            "product_ids": [MILK_ID, _ARLA_ID],
            "quantity": 1000,
            "unit": "L",
        },
    )
    assert offer["lines"][0]["brand"] == "Valio"
